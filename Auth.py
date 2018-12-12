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

    def requestAvatar(self, avatarId, mind, *interfaces):
        """
        Requests that this Realm shall provide an "avatarAspect" which implements
        one of some list of interfaces. What this means for us is that we will
        create and return an SSHUser instance (which implements IConchUser).

        avatarId: the username which we are getting an instance for.
        mind: an object that implements a client-side interface for this Realm.
            In practical terms, this is some object that is provided by our

        interfaces: list of interfaces that the mind is compatible with. In our
            case this is only ever going to be IConchUser, so we don't really care.
        """
        if IConchUser in interfaces:
            # Return a tuple of (interface, avatarAspect, logout).
            # interface: one of the interfaces passed in.
            # avatarAspect: an instance of a class that implements that interface.
            # logout: a callable which will "detach the mind from the avatar". Spooky.
            avatar = SSHUser(self.world, avatarId)
            return interfaces[0], avatar, avatar.logout
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
        self.user_is_known = self.auth.transport.factory.portal.realm.world.db.user_exists(username)
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
        log.info("{0} service starting".format(self.name) )
        self.state = None
        self.state_changes = 0
        self.packet_count = 0

        # Stores the user's public keys, if they provided any.
        self.seen_keys = []


        self.send_banner("HERE BE DRAGONS!\nThis software is highly experimental. Try not to break it.\nDebug logging is enabled. DO NOT enter any real passwords!\n")

    def ssh_USERAUTH_REQUEST(self, packet):
        """
        This method is called when a packet is received.
        The client has requested authentication.  Payload::
            string user
            string next service
            string method
            <authentication specific data>
        @type packet: L{bytes}
        """
        self.packet_count += 1
        user, nextService, method, rest = getNS(packet, 3)
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
            self.send_disconnect("You are doing that too much!")

        #log.debug( "Auth request for user {0}, service {1}, method {2}.".format(user, nextService, method) )

        if self.state.user_is_known:
            # Username is known to us! Do normal login.
            if first:
                self.supportedAuthentications = ["publickey",
                    "keyboard-interactive", "password", "test"]
            return tryAuth( method, rest )

        #log.debug(self.supportedAuthentications)
        if method == "publickey":
            # User is not known, store their pubkeys so they can
            #   use one to register with us.
            log.debug(  "Pubkey attempt")
            return self.store_pubkey( rest )
        elif method == "keyboard-interactive":
            log.debug( "Interactive attempt")
            return self.tryKeyboardInteractive(rest)
        elif method == "password":
            if not self.state.user_is_known:
                # We told this client we don't support passwords
                # but they are ignoring us
                self.send_disconnect("This auth method is not allowed")
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

    def tryKeyboardInteractive(self, packet):
        self.askQuestions([
            #("\033[1mWelcome, \033[36m{0}\033[39m!\033[0m I don't recognise your username.\nWould you like to \033[4mr\033[0megister, proceed as a \033[4mg\033[0muest, or \033[4mq\033[0muit?\n(r/g/q): ".format(self.state.username), False)
            ("Welcome, {0}! I don't recognise your username.\nWould you like to [r]egister, proceed as a [g]uest, or [q]uit?\n(r/g/q): ".format(self.state.username), False)
        ])

    def ssh_USERAUTH_INFO_RESPONSE(self, packet):
        """
        The user has responded with answers to our questions.
        """
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
        else:
            log.debug( "Responses: {0}".format( repr(resp) ) )
            if self.state.phase == 0:
                r = resp[0][0].lower()
                if( r == "r" ):
                    self.state.phase += 1
                    self.askQuestions([
                        #("You are registering with the username \033[1;36m{0}\033[0m.\nPlease choose a password: ".format(self.state.username), True),
                        ("You are registering with the username: {0}\nPlease choose a password: ".format(self.state.username), True),
                        ("Please re-type the password: ", True)
                    ])
                elif r == "q":
                    self.noAuthLeft("Please come back soon!")
                elif r == "g":
                    self.askQuestions([
                        ("Sorry, guest mode actually isn't implemented yet.\nRegister or quit? (r/q): ", False) ])
                else:
                    self.askQuestions([
                        ("Sorry, I don't understand your input.\nRegister, vidit as guest or quit? (r/g/q): ", False) ])
            elif self.state.phase == 1:
                if resp[0] != resp[1]:
                    self.askQuestions([
                        ("Those passwords didn't match!\nPlease choose a password: ".format(self.state.username), True),
                        ("Please re-type the password: ", True)
                    ])
                else:
                    self.state.phase += 1
                    self.askQuestions([
                        ("Choose a name for your first character: ", False)
                        ])
            else:
                #d.callback(resp)
                self.send_banner("This has been a test. No actual registration has been made.")
                self.noAuthLeft("Auth test complete" )
    
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
        log.info("Disconnecting user {0}".format(self.state.username))
        self.transport.sendDisconnect(
            transport.DISCONNECT_HOST_NOT_ALLOWED_TO_CONNECT,
            msg)

    def succeedAuth(self, service):
        # Authentication has succeeded fully.
        self.transport.sendPacket(MSG_USERAUTH_SUCCESS, b'')
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

