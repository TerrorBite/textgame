# Twisted imports
from zope.interface import implements, implementer
from twisted.conch.interfaces import IConchUser
from twisted.cred import portal
from twisted.conch.ssh.common import NS, getNS
from twisted.conch.ssh import service, transport, userauth

# Python imports
import struct

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
        if IConchUser in interfaces:
            return interfaces[0], SSHUser(self.world, avatarId), lambda: None
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


class UserAuthService(DebugSSHService):
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
    supportedAuthentications = ["publickey", "password", "keyboard-interactive"]

    protocolMessages = userauth.SSHUserAuthServer.protocolMessages

    def serviceStarted(self):
        log.info("{0} service starting".format(self.name) )
        self.user = None
        self.nextService = None

        # Stores the user's public key, if they provided one.
        self.pubKey = None

        self.phase = 0

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
        user, nextService, method, rest = getNS(packet, 3)
        if user != self.user or nextService != self.nextService:
            self.authenticatedWith = [] # clear auth state
            log.debug(dir(self.transport.factory.portal))
            self.new_user = self.transport.factory.portal.realm.world.db.user_exists(user)
        self.user = user
        self.nextService = nextService

        log.debug( "Auth request for user {0}, service {1}, method {2}.".format(user, nextService, method) )

        if method == "publickey":
            # If user is known, try and do pubkey auth.
            # If user is not known, store their pubkeys so they can
            #   use one to register with us.
            #self.auth_pubkey( rest )
            log.debug(  "Pubkey attempt")
            #return self.continueNextAuth(self.supportedAuthentications)
            return self.failAuth(self.supportedAuthentications)
        elif method == "password":
            # If user account exists, 
            # but in all cases, reject with partial success
            # and with can continue of interactive
            log.debug( "Password attempt")
            return self.continueNextAuth(self.supportedAuthentications)
        elif method == "keyboard-interactive":
            log.debug( "Interactive attempt")
            return self.tryKeyboardInteractive(rest)
        else:
            return self.failAuth(self.supportedAuthentications)
    
    def firstContact(self):
        """
        Called the first time a user sends us a userauth request.
        """

    def tryKeyboardInteractive(self, packet):
        self.askQuestions([
            ("I haven't seen you before. Do you want to register (yes/no)? ", False)
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
            if self.phase == 0:
                if( resp[0].lower() == "yes" ):
                    self.phase += 1
                    self.askQuestions([
                        ("Please choose a password: ", True),
                        ("Please re-enter your password: ", True)
                    ])
            else:
                #d.callback(resp)
                log.debug( "Responses: {0}".format( repr(resp) ) )
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
    def succeedAuth(self):
        # Authentication has succeeded fully.
        pass
