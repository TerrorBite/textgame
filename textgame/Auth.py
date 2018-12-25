# Twisted imports
from zope.interface import implements, implementer
from twisted.conch.interfaces import IConchUser
from twisted.cred import portal
from twisted.conch.ssh.common import NS, getNS
from twisted.conch.ssh import service, transport, userauth

# Python imports
import struct
from base64 import b64encode

# Our imports
from Util import log
from User import SSHUser

class SSHRealm:
    """
    This simple realm generates User instances.

    This is basically a factory for SSHUser instances. After SSH authentication
    has succeeded, the SSHRealm is provided with the username of the account that
    just logged in, and uses it to create and return an appropriate User instance.

    This is an old-style class because Twisted doesn't use new-style classes.
    """
    implements(portal.IRealm)

    def __init__(self, world):
        self.world = world

    def doesAvatarExist(self, avatarId):
        """
        Returns True if this avatar ID is valid, otherwise false.
        """
        # Query the database as to whether the username exists.
        return self.world.db.username_exists(avatarId)

    def requestAvatar(self, avatarId, mind, *interfaces):
        """
        Requests that this Realm shall provide an "avatarAspect" which implements
        one of some list of interfaces. What this means for us is that we will
        create and return an SSHUser instance (which implements IConchUser).

        avatarId: the username which we are getting an instance for.
        mind: an object that implements a client-side interface for this Realm.
            This is an object provided by our UserAuthService, and we actually
            abuse this to pass in the character name.
        interfaces: list of interfaces that the mind is compatible with. In our
            case this is only ever going to be IConchUser, so we don't really care.
        """
        if IConchUser in interfaces:
            # Return a tuple of (interface, avatarAspect, logout).
            # interface: one of the interfaces passed in.
            # avatarAspect: an instance of a class that implements that interface.
            # logout: a callable which will "detach the mind from the avatar". Spooky.
            avatar = SSHUser(self.world, avatarId, mind)
            logout = avatar.on_logout if hasattr(avatar, "on_logout") and \
                    callable(avatar.on_logout) else lambda: None
            return interfaces[0], avatar, logout
        else:
            log.error("SSHRealm: No supported interfaces")
            raise NotImplementedError("No supported interfaces found.")


class DebugSSHService(service.SSHService):
    """
    This replacement for the Conch SSHService simply logs
    a debug message for every packet received, with no
    changes in functionality. Used to debug subclasses of
    the Conch SSHService.
    """
    def packetReceived(self, messageNum, packet):
        log.trace("{0}: packet {1} ({2}): {3}".format(
            self.name, messageNum, self.protocolMessages[messageNum], repr(packet)
            ) )
        service.SSHService.packetReceived(self, messageNum, packet)

class UserAuthState(object):
    def __init__(self, auth, username, service):
        self.auth = auth
        self.pubkeys = []
        self.username = username
        self.desired_service = service
        # the following line is terrifying
        self.user_is_known = self.auth.portal.realm.doesAvatarExist(username)
        # Stores phase of interactive auth
        self.phase = 0

    def is_invalid(self, username, service):
        """
        Returns True if the supplied username and service name
        don't match stored values, which means this state is invalid.
        """
        return not all((username == self.username,
                service == self.desired_service))

    def add_key(self, blob):
        self.pubkeys.append(blob)

    def begin_interactive(self):
        self._interactive = KeyboardInteractiveStateMachine(self.auth, self.username)
    
    def continue_interactive(self, responses):
        self._interactive(responses)

class UserAuthService(service.SSHService):
    """
    The UserAuthService replaces the standard SSH authentication
    service. This service customises the login experience in the
    following ways:

    - Unknown usernames are not rejected, instead, the
      keyboard-interactive method is used to offer the user a
      chance to register an account.
    - Unknown users who offered an SSH pubkey during authentication
      will be asked if they wish to use that key to authenticate in future.
    - Known users will be authenticated via pubkey, password, or
      keyboard-interactive.
    - Known users will be asked which character they want to play.
    
    Additionally:
    - On the internet, bots constantly attempt to brute-force SSH
      server passwords. This service may include defences against
      such connections.
    """
    #Here, we completely customise the SSH login experience.

    # Name of this SSH service.
    name = "ssh-userauth"
    supportedAuthentications = ["publickey", "keyboard-interactive"]

    protocolMessages = userauth.SSHUserAuthServer.protocolMessages

    def serviceStarted(self):
        """
        Called when the service is started. This service starts automatically
        as soon as a user connects, in order to authenticate the user.
        """
        #log.info("{0} service starting".format(self.name) )
        # Begin with no state.
        self.state = None
        # Store the portal for convenience. We use the portal for authentication.
        self.portal = self.transport.factory.portal
        # Keep track of a few values so that we can combat bots.
        self.state_changes = 0
        self.packet_count = 0

        self.ip = self.transport.transport.getPeer().host

        # Send login banner.
        self.send_banner(self.transport.factory.bannerText)

    def serviceStopped(self):
        log.debug("Auth Service for {0} stopping".format(self.ip))

    def isBadUsername(self, user):
        is_bad = user.lower() in ("root", "admin", "ubnt", "support", "user", "pi")
        if is_bad:
            log.info('Disconnecting "{0}" from {1}: blacklisted username'.format(user, self.ip))
            self.transport.sendDisconnect(
                transport.DISCONNECT_ILLEGAL_USER_NAME,
                "You can't use that username ({0}) here. Please reconnect using a different one.".format(user))
        return is_bad

    def ssh_USERAUTH_REQUEST(self, packet):
        """
        This method is called when a packet is received.
        The client has requested authentication.  Payload:
            string user
            string next service
            string method
            [authentication specific data]
        """
        self.packet_count += 1
        user, nextService, method, rest = getNS(packet, 3)
        if self.isBadUsername(user): return
        first = False
        if self.state is None or self.state.is_invalid( user, nextService ):
            # If username or desired service has changed during auth,
            # the RFC says we must discard all state.
            self.state = UserAuthState( self, user, nextService )
            # We do keep track of how many state changes there have been.
            # This is used to thwart bots.
            self.state_changes += 1
            #log.debug(dir(self.transport.factory.portal))
            self.firstContact()
            first = True
        if self.state_changes > 3 or self.packet_count > 20:
            log.info("Disconnecting user: too many attempts")
            self.send_disconnect("You are doing that too much!")

        #log.debug( "Auth request for user {0}, service {1}, method {2}.".format(user, nextService, method) )

        if self.state.user_is_known:
            # Username is known to us! Do normal login.
            if first:
                self.supportedAuthentications = ["publickey",
                    "keyboard-interactive", "password"]
            return tryAuth( method, rest )

        #log.debug(self.supportedAuthentications)
        if method == "publickey":
            # User is not known, store their pubkeys so they can use one to register with us.
            log.debug( "Pubkey attempt" )
            return self.store_pubkey( rest )
        elif method == "keyboard-interactive":
            log.debug( "Interactive attempt")
            return self.beginKeyboardInteractive(rest)
        elif method == "password":
            if not self.state.user_is_known:
                # We told this client we don't support passwords
                # but they are ignoring us
                log.info("Disconnecting user: illegal password attempt")
                self.send_disconnect("This auth method is not allowed")
                self.transport.factory.banHost(self.ip)
            else:
                log.debug( "Denying password attempt".format(method) )
                self.failAuth(self.supportedAuthentications)
        else:
            log.debug( "Unknown {0} attempt".format(method) )
            return self.failAuth(self.supportedAuthentications)
    
    def firstContact(self):
        """
        Called the first time a user sends us a userauth request.
        """
        known_text = "Known" if self.state.user_is_known else "Unknown"
        log.info("{0} user {1} is authenticating".format(known_text, self.state.username))

    def auth_pubkey(self, pubkey):
        log.debug("Got a pubkey")

    def store_pubkey(self, pubkey):
        algo, blob, rest = getNS(pubkey[1:], 2)
        self.state.add_key(blob)
        log.debug( self.key2str(algo, blob) )
        # Tell client that this key didn't auth them
        self.failAuth(self.supportedAuthentications)

    def key2str(self, algo, blob):
        return "{0} {1}".format(algo, b64encode(blob))

    def beginKeyboardInteractive(self, packet):
        self.state.begin_interactive()

    def ssh_USERAUTH_INFO_RESPONSE(self, packet):
        try:
            resp = []
            numResps = struct.unpack('>L', packet[:4])[0]
            packet = packet[4:]
            while len(resp) < numResps:
                response, packet = getNS(packet)
                resp.append(response)
            if packet:
                #raise error.ConchError("%i bytes of extra data" % len(packet))
                log.warn( "%i bytes of extra data" % len(packet))
                # Ignore extra data
        except:
            #d.errback(failure.Failure())
            pass
        self.state.continue_interactive(resp)
    
    def askQuestions(self, questions):
        resp = []
        for message, isPassword in questions:
            resp.append((message, 0 if isPassword else 1))
        packet = NS('') + NS('') + NS('')
        packet += struct.pack('>L', len(resp))
        for prompt, echo in resp:
            packet += NS(prompt)
            packet += chr(echo)
        self.transport.sendPacket(userauth.MSG_USERAUTH_INFO_REQUEST, packet)
        log.debug("Asked the user questions")

    def doGuestLogin(self):
        """
        Log the user in to a guest character.
        """
        #TODO: This currently logs in to the admin account.
        # This needs to log in to a guest character, by requesting
        # an avatar with IConchGuestUser or similar.
        (_, self.transport.avatar, self.transport.logoutFunction) = \
                self.portal.realm.requestAvatar("admin", "The Creator", IConchUser)
        service = self.transport.factory.getService(self.transport,
                self.state.desired_service)
        self.succeedAuth(service)

    def send_banner(self, banner):
        self.transport.sendPacket(userauth.MSG_USERAUTH_BANNER,
                NS(banner+'\n') + NS("en-US"))

    def continueNextAuth(self, remaining):
        # This auth attempt wasn't immediately successful.
        self.transport.sendPacket(userauth.MSG_USERAUTH_FAILURE,
                NS(','.join(remaining)) + '\xff')
    
    def failAuth(self, remaining):
        self.transport.sendPacket(userauth.MSG_USERAUTH_FAILURE,
                NS(','.join(remaining)) + '\x00')

    def noAuthLeft(self, msg):
        self.transport.sendDisconnect(
            transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE,
            msg)

    def send_disconnect(self, msg):
        log.info("Disconnecting {0}".format(self.ip))
        self.transport.sendDisconnect(
            transport.DISCONNECT_HOST_NOT_ALLOWED_TO_CONNECT,
            msg)

    def succeedAuth(self, service):
        # Authentication has succeeded fully.
        self.transport.sendPacket(userauth.MSG_USERAUTH_SUCCESS, b'')
        self.transport.setService(service())

    def _cbFinishedAuth(self, result):
        """
        The callback when user has successfully been authenticated.  For a
        description of the arguments, see L{twisted.cred.portal.Portal.login}.
        We start the service requested by the user.
        """
        (interface, avatar, logout) = result
        self.transport.avatar = avatar
        self.transport.logoutFunction = logout
        service = self.transport.factory.getService(self.transport,
                self.state.desired_service)
        if not service:
            raise error.ConchError('could not get next service: %s'
                                  % self.nextService)
        log.msg('%r authenticated with %r' % (self.state.username, None))
        self.succeedAuth(service)

class KeyboardInteractiveStateMachine(object):
    def __init__(self, auth, username):
        """
        Constructor. Pass in a method that this state machine can use to ask the user questions.
        """
        self.auth = auth

        # Get the generator that forms our state machine
        self._state = self._interactive(username)

        # Invoke its first run
        auth.askQuestions( self._state.next() )

        self._outcome = False

    def __call__(self, responses=[]):
        self.responses = responses
        try:
            self.auth.askQuestions( self._state.next() )
        except StopIteration as e:
            return self._outcome
        return True

    def _interactive(self, username):
        """
        This method is a generator. It yields messages that should be asked.
        After each yield, self.responses should contain the answers to the question.
        """
        #("\033[1mWelcome, \033[36m{0}\033[39m!\033[0m I don't recognise your username.\nWould you like to \033[4mr\033[0megister, proceed as a \033[4mg\033[0muest, or \033[4mq\033[0muit?\n(r/g/q): ".format(self.state.username), False)
        yield [("Welcome, {0}! I don't recognise your username.\nWould you like to [r]egister, proceed as a [g]uest, or [q]uit?\n(r/g/q): ".format(username), False)]
        choice = self.responses[0].lower()

        while len(choice)==0 or choice[0] not in "rgq":
            yield [ ("Sorry, I don't understand your input.\nRegister, visit as a guest or quit? (r/g/q): ", False) ]
            choice = self.responses[0].lower()
        
        if choice == "q":
            self.auth.send_banner("Goodbye!")
            self.auth.noAuthLeft("Please come again soon!")
            return
        elif choice == "g":
            yield [("Please choose a name for your temporary character: ", False)]
            charname = self.responses[0]
            self.auth.doGuestLogin()
            return

        elif choice == "r":
            yield [
                #("You are registering with the username \033[1;36m{0}\033[0m.\nPlease choose a password: ".format(self.state.username), True),
                ("You are registering with the username: {0}\nPlease choose a password: ".format(username), True),
                ("Please re-type the password: ", True)
            ]
            resp = self.responses
            while resp[0] != resp[1]:
                yield [
                    ("Those passwords didn't match!\nPlease choose a password: ", True),
                    ("Please re-type the password: ", True)
                ]
                resp = self.responses
            password = resp[0]
            yield [("Choose a name for your first character: ", False)]
            name = self.responses[0]

            self.auth.send_banner("Sadly, character creation isn't implemented yet.")
            self.auth.noAuthLeft("Please visit again soon!")
