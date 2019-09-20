from zope.interface import implements, implementer

from twisted.internet import protocol
from twisted.conch.checkers import SSHPublicKeyChecker
from twisted.conch.ssh import factory as conch_factory
from twisted.conch.ssh import userauth, connection, keys, session
from twisted.conch.ssh.address import SSHTransportAddress

from textgame.Util import log, LogLevel, enum

from textgame import World, Things
from User import SSHUser, IUserProtocol, State
from Auth import SSHRealm, UserAuthService

class BareUserProtocol(protocol.Protocol):
    implements(IUserProtocol)
    """
    Processes a basic user session - a raw connection with no UI presented to the user.
    """

    # TODO: This code needs to be completely rewritten.

    def __init__(self, user=None):
        self.user = user
        self.buf = ''
        self.sshmode = False

    def connectionMade(self):
        h = self.transport.getHost()
        log(LogLevel.Info, "Incoming connection from {0}".format(h))

    def dataReceived(self, data):
        "When data is received, process it according to state."
        if self.sshmode:
            # TODO: Is "sshmode" ever used now that everything is split out into SSHProtocol?
            self.transport.write(data)
            if data == '\r': self.transport.write('\n')
            data = data.translate('\r', '\n')
            # Split to completed lines
            lines = filter(len, data.split('\n')) # eliminate empty lines
            lines[0] = self.buf+lines[0]
            self.buf = lines[-1]
            for line in lines[:-1]: self.process_line(line.strip())
        else:
            log(LogLevel.Debug, "Received data without terminating newline, buffering: {0}".format(repr(data)))
            self.buf += data

class BasicUserSession(protocol.Protocol):
    """
    This code is non-functional. Do not use it.
    """
    def __init__(self, avatar=None):
        self.player = None
        self.buf = ''
        self.avatar = avatar

    def connectionMade(self):
        h = self.transport.getHost()
        if type(h) is SSHTransportAddress:
            self.sshmode = True
            h = h.address
        log(LogLevel.Info, "Incoming connection from {0}".format(h))
        self.host = h.host
        if self.avatar:
            self.player = self.world.connect(self.avatar.username)
            self.complete_login()


    def connectionLost(self, data):
        if self.my_state < State.LoggedIn:
            pass
            log(LogLevel.Info, "{0} lost connection: {1}".format(self.host, data.getErrorMessage()))
        else:
            try: 
                log(LogLevel.Info, "{0}#{1} [{2}] lost connection: {3}".format(self.player.name, self.player.id, self.host, data.getErrorMessage()))
            except:
                log(LogLevel.Info, "<UNKNOWN> {0} lost connection: {1}".format(self.host, data.getErrorMessage()))



def create_ssh_factory(world):
    """
    Creates and returns a factory class that produces SSH sessions.

    This function is responsible for loading the SSH host keys that our
    SSH server will use, or generating them if they do not exist (if possible).

    The reason why we have a double-factory setup is twofold:
    
    First, we need to dynamically load (or maybe generate) SSH host keys, and for
    some reason, Twisted's SSHFactory seems to require the SSH keys to be present
    as class attributes. The connection and userauth classes to use also need to
    be set this way.

    Second, this allows us to create a separate SSHFactory per world, should we ever
    run more than one world on a single server.
    """

    import os, sys
    from twisted.python.procutils import which
    if not os.path.exists('host_rsa'):
        if not sys.platform.startswith('linux'):
            log(LogLevel.Error, "SSH host keys are missing and I don't know how to generate them on this platform")
            log(LogLevel.Warn, 'Please generate the files "host_rsa" and "host_rsa.pub" for me.')
            raise SystemExit(1)
        log(LogLevel.Warn, 'SSH host keys are missing, invoking ssh-keygen to generate them')
        paths = which('ssh-keygen')
        if len(paths) == 0:
            log(LogLevel.Error, 'Could not find ssh-keygen on this system.')
            log(LogLevel.Warn, 'Please generate the files "host_rsa" and "host_rsa.pub" for me.')
            raise SystemExit(1)
        ret = os.spawnl(os.P_WAIT, paths[0], 'ssh-keygen', '-q', '-t', 'rsa', '-f', 'host_rsa', '-P', '', '-C', 'textgame-server')
        if ret != 0:
            log(LogLevel.Error, 'Failed generating SSH host keys. Is ssh-keygen installed on this system?')
            raise SystemExit(1)
        else:
            log(LogLevel.Info, 'Successfully generated SSH host keys')
            
    publicKey = file('host_rsa.pub', 'r').read()
    privateKey = file('host_rsa', 'r').read()

    # Global ban list shared by all factories.
    banlist = []

    from textgame.db import Credentials
    from twisted.cred.portal import Portal
    class SSHFactory(conch_factory.SSHFactory):
        """
        Factory responsible for generating SSHSessions.

        This SSHFactory is functionally identical to the built-in Conch
        SSHFactory, but is pre-configured with our SSH host keys.

        We also configure the SSHFactory with the services we are providing.
        In this case we are using our UserAuthService (a subclass of the
        built-in Conch SSHUserAuthServer) to authenticate users, and the
        built-in SSHConnection class to handle incoming connections.
        The built-in classes are configured via the
        Portal that is stored in the portal attribute.
        """
        publicKeys = {
                'ssh-rsa': keys.Key.fromString(data=publicKey)
                }
        privateKeys = {
                'ssh-rsa': keys.Key.fromString(data=privateKey)
                }
        services = {
                'ssh-userauth': UserAuthService,
                'ssh-connection': connection.SSHConnection
                }

        # We should really be getting this motd from the world instance
        bannerText = "HERE BE DRAGONS!\nThis software is highly experimental." + \
        "Try not to break it.\nDebug logging is enabled. DO NOT enter any real passwords!\n"

        # This Portal is the conduit through which we authenticate users.
        # The SSHRealm will generate user instances after auth succeeds.
        portal = Portal(SSHRealm(world), [
            # This checker allows the Portal to verify passwords.
            Credentials.CredentialsChecker(world.db),
            # This checker allows the Portal to verify SSH keys.
            SSHPublicKeyChecker(
                Credentials.AuthorizedKeystore(world.db)),
            # This "checker" will create a new user, instead of
            # authenticating an existing one.
            #Database.NewUserCreator(world.db)
        ])

        def buildProtocol(self, addr):
            # Reject this connection if the IP is banned.
            if addr.host in banlist:
                log.info("Rejecting connection from banned IP {0}".format(addr.host))
                return None
            # otherwise all good; let superclass do the rest
            log.info("Incoming SSH connection from {0}".format(addr.host))
            return conch_factory.SSHFactory.buildProtocol(self, addr)

        def banHost(self, host, duration=None):
            """
            Bans a host from connecting.
            """
            #TODO: Timed bans?
            log.info("Banning IP {0}".format(host))
            banlist.append(host)

    return SSHFactory()
    # End of SSH host key loading code

