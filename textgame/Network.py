import socket
import struct
from typing import List, Tuple, Dict

from zope.interface import implementer

from twisted.internet import protocol
from twisted.conch.checkers import SSHPublicKeyChecker
from twisted.conch.ssh import factory as conch_factory
from twisted.conch.ssh import connection, keys
from twisted.conch.ssh.address import SSHTransportAddress

from textgame.Util import get_logger

from textgame.User import State
from textgame.interfaces import IUserProtocol
from textgame.Auth import SSHRealm, UserAuthService

logger = get_logger(__name__)


def ip2int(ip_addr: str) -> int:
    return struct.unpack("!I", socket.inet_aton(ip_addr))[0]


def int2ip(n: int) -> str:
    """
    Converts an integer to the string representation of an IP address.
    """
    return socket.inet_ntoa(struct.pack("!I", n))


@implementer(IUserProtocol)
class BareUserProtocol(protocol.Protocol):
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
        logger.info("Incoming connection from {0}".format(h))

    def dataReceived(self, data):
        "When data is received, process it according to state."
        if self.sshmode:
            # TODO: Is "sshmode" ever used now that everything is split out into SSHProtocol?
            self.transport.write(data)
            if data == '\r':
                self.transport.write('\n')
            data = data.translate('\r', '\n')
            # Split to completed lines
            lines: List[str] = list(filter(len, data.split('\n')))  # eliminate empty lines
            lines[0] = self.buf+lines[0]
            self.buf = lines[-1]
            for line in lines[:-1]:
                self.process_line(line.strip())
        else:
            logger.debug("Received data without terminating newline, buffering: {0}".format(repr(data)))
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
        logger.info("Incoming connection from {0}".format(h))
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


class SSHShellOnlyConnection(connection.SSHConnection):
    """
    TODO: Document this
    """
    def getChannel(self, channelType, windowSize, maxPacket, data):
        channel = self.transport.avatar.lookupChannel(channelType, windowSize, maxPacket, data)


def get_rsa_server_keys() -> Tuple[keys.Key, keys.Key]:
    """
    Gets the SSH private and public keys, generating them if they do not exist.

    :return: The private and public keys.
    """
    try:
        # Load existing keys
        return keys.Key.fromFile('host_rsa'), keys.Key.fromFile('host_rsa.pub')

    except (FileNotFoundError, keys.BadKeyError):
        # Keys need to be generated.
        private_key, public_key = generate_rsa_server_keys()

        return keys.Key.fromString(private_key), keys.Key.fromString(public_key)


def generate_rsa_server_keys() -> Tuple[bytes, bytes]:
    """
    Generates SSH server keys using RSA, writes them to the correct files, then returns the bytes that were written.

    This will overwrite any existing key files.

    :return: The bytes of the private key, and the bytes of the public key.
    """
    from cryptography.hazmat.primitives import serialization as crypto_serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend as crypto_default_backend

    # Generate the key
    key = rsa.generate_private_key(
        backend=crypto_default_backend(),
        public_exponent=65537,
        key_size=2048
    )

    # Get the private key in the standard PEM/PKCS8 format for SSH private keys.
    private_key = key.private_bytes(
        crypto_serialization.Encoding.PEM,
        crypto_serialization.PrivateFormat.PKCS8,
        crypto_serialization.NoEncryption())

    # Get the public key in the standard OpenSSH format.
    public_key = key.public_key().public_bytes(
        crypto_serialization.Encoding.OpenSSH,
        crypto_serialization.PublicFormat.OpenSSH
    )

    # Write the two keys.
    with open('host_rsa', 'wb') as f:
        f.write(private_key)

    with open('host_rsa.pub', 'wb') as f:
        f.write(public_key)

    # Return them.
    return private_key, public_key


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

    # Global ban list shared by all factories.
    # TODO: persist this
    ban_list = set([])

    # Get the keys we will need.
    private_key, public_key = get_rsa_server_keys()

    from textgame.db import Credentials
    from twisted.cred.portal import Portal

    # noinspection PyPep8Naming
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

        services = {
            b'ssh-userauth': UserAuthService,
            b'ssh-connection': connection.SSHConnection
        }

        # This Portal is the conduit through which we authenticate users.
        # The SSHRealm will generate user instances after auth succeeds.
        # We pass a list of instances to the SSHRealm; the realm will use these to verify credentials
        # which are presented by the user.
        portal = Portal(SSHRealm(world), [

            # This checker allows the Portal to verify passwords and create new users.
            Credentials.DBCredentialsChecker(world),

            # This checker allows the Portal to verify SSH keys.
            SSHPublicKeyChecker(Credentials.AuthorizedKeystore(world.db)),
        ])

        def getPublicKeys(self) -> Dict[bytes, keys.Key]:
            return {
                b'ssh-rsa': public_key
            }

        def getPrivateKeys(self) -> Dict[bytes, keys.Key]:
            return {
                b'ssh-rsa': private_key
            }

        @property
        def bannerText(self):
            # We should really be getting this motd from the world instance
            return "HERE BE DRAGONS!\nThis software is highly experimental." + \
                   "Try not to break it.\nDebug logging is enabled. DO NOT enter any real passwords!\n"

        def buildProtocol(self, address):
            """
            Build an SSHServerTransport for this connection.

            :param address: A :class:`twisted.internet.interfaces.IAddress` provider, representing the IP address
                of the client connecting to us.
            :return: A :class:`SSHServerTransport` instance, or None if the connection should be rejected..
            """
            # Reject this connection if the IP is banned.
            if ip2int(address.host) in ban_list:
                logger.verbose("Rejecting connection from banned IP {0}".format(address.host))
                # This will send a RST packet
                return None
            # otherwise all good; let superclass do the rest
            logger.verbose("Incoming SSH connection from {0}".format(address.host))
            return conch_factory.SSHFactory.buildProtocol(self, address)

        @staticmethod
        def ban_host(host, duration=None):
            """
            Bans a host from connecting.
            """
            # TODO: Timed bans?
            logger.verbose("Banning IP {0}".format(host))
            ban_list.add(ip2int(host))

    return SSHFactory()
    # End of SSH host key loading code

