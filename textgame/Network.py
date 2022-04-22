import socket
import struct
import textwrap
import warnings
from typing import List, Tuple, Dict

import twisted.conch.ssh.transport
from zope.interface import implementer

from twisted.internet import protocol
from twisted.conch.checkers import SSHPublicKeyChecker
from twisted.conch.ssh import factory as conch_factory, common
from twisted.conch.ssh import connection, keys
from twisted.conch.ssh.address import SSHTransportAddress
from twisted.cred.portal import Portal

from textgame.Util import get_logger

from textgame.User import State, SSHUser
from textgame.interfaces import IUserProtocol
from textgame.Auth import SSHRealm, UserAuthService
from textgame.db import Credentials

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

    This is not currently used.
    """

    # TODO: This code needs to be completely rewritten or removed.

    def __init__(self, user=None):
        warnings.warn("Not used - needs rewrite.", DeprecationWarning)

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
            data = data.translate(b'\r', b'\n')
            # Split to completed lines
            lines: List[str] = list(filter(len, data.split(b'\n')))  # eliminate empty lines
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
        self.sshmode = False
        self.host = None

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

    def connectionLost(self, reason=protocol.connectionDone):
        if self.my_state < State.LoggedIn:
            logger.info(f"{self.host} lost connection: {reason.getErrorMessage()}")
        else:
            if self.player:
                logger.info(f"{self.player.name}#{self.player.id} [{self.host}] "
                            f"lost connection: {reason.getErrorMessage()}")
            else:
                logger.info(f"{self.host} lost connection: {reason.getErrorMessage()}")


class SSHShellOnlyConnection(connection.SSHConnection):
    """
    This SSHConnection rejects "session" channel requests of type "exec",
    while allowing channel requests of type "shell".
    """

    def ssh_CHANNEL_REQUEST(self, packet):
        local_channel = struct.unpack(">L", packet[:4])[0]
        request_type, rest = common.getNS(packet[4:])
        # want_reply = "" if ord(rest[0:1]) else " (noreply)"
        # logger.debug(f"CHANNEL_REQUEST: Channel {local_channel} request{want_reply}: {request_type}; "
        #              f"args: {rest[1:]!r}")

        if request_type == b"exec":
            # send a MSG_CHANNEL_REQUEST_FAILURE
            logger.info("Rejecting an attempt to execute a command.")
            self._ebChannelRequest(None, local_channel)
            # self.transport.sendDisconnect(twisted.conch.ssh.transport.DISCONNECT_SERVICE_NOT_AVAILABLE,
            #                               "Command execution is not supported on this server.")
            return 0
        return super().ssh_CHANNEL_REQUEST(packet)


def get_rsa_server_keys() -> Tuple[keys.Key, keys.Key]:
    """
    Gets the SSH RSA private and public keys, generating them if they do not exist.

    :return: A tuple of (private key, public key).
    """
    try:
        # Load existing keys
        return keys.Key.fromFile('host_rsa'), keys.Key.fromFile('host_rsa.pub')

    except (FileNotFoundError, keys.BadKeyError):
        # Keys need to be generated.
        private_key, public_key = generate_rsa_server_keys()
        logger.info("New server keys were generated.")

        return (
            keys.Key.fromString(private_key, type="PRIVATE_OPENSSH"),
            keys.Key.fromString(public_key)
        )


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
        crypto_serialization.PrivateFormat.OpenSSH,
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


# TODO: persist this across restarts somehow
#: Global ban list shared by all factories.
global_ban_list = set()


# noinspection PyPep8Naming
class SSHFactory(conch_factory.SSHFactory):
    """
    Factory responsible for generating SSHSessions.

    This SSHFactory is based upon the built-in Conch SSHFactory, but with extra functionality:

    * Loads the RSA host keys from disk when instantiated
    * Takes a world parameter, allowing multiple worlds to potentially be hosted in one server instance
    * Configures the Portal to be used, creating the Realm and other checkers
    * Sets the banner text to be sent on connect
    * Ability to ban IP addresses from connecting

    We also configure the SSHFactory with the services we are providing.
    In this case we are using our UserAuthService (a subclass of the
    built-in Conch SSHUserAuthServer) to authenticate users, and the
    built-in SSHConnection class to handle incoming connections.
    The built-in classes are configured via the
    Portal that is stored in the portal attribute.
    """

    def __init__(self, world):
        self.world = world
        self._rsa_key, self._rsa_pub = get_rsa_server_keys()

        # This Portal is the conduit through which we authenticate users.
        # The SSHRealm will generate user instances after auth succeeds.
        # We pass a list of instances to the SSHRealm; the realm will use these to verify credentials
        # which are presented by the user.
        self.portal = Portal(SSHRealm(world), [

            # TODO: A checker which can create accounts.
            # This checker allows the Portal to verify passwords and create new users.
            Credentials.DBCredentialsChecker(world),

            # This checker allows the Portal to verify SSH keys.
            SSHPublicKeyChecker(Credentials.AuthorizedKeystore(world.db)),
        ])

    services = {
        b'ssh-userauth': UserAuthService,
        # b'ssh-connection': connection.SSHConnection
        b'ssh-connection': SSHShellOnlyConnection
    }

    def getPublicKeys(self) -> Dict[bytes, keys.Key]:
        return {
            b'ssh-rsa': self._rsa_pub
        }

    def getPrivateKeys(self) -> Dict[bytes, keys.Key]:
        return {
            b'ssh-rsa': self._rsa_key
        }

    primes_path = '/etc/ssh/moduli'

    def getPrimes(self):
        """
        Return dictionary with primes number.
        Reads prime numbers from OpenSSH compatible moduli file.
        """
        primes_file = open(self.primes_path, 'r')
        try:
            primes = {}
            for line in primes_file:
                line = line.strip()
                if not line or line[0] == '#':
                    continue
                tim, typ, tst, tri, size, gen, mod = line.split()
                size = int(size) + 1
                gen = int(gen)
                mod = int(mod, 16)
                if size not in primes:
                    primes[size] = []
                primes[size].append((gen, mod))
            return primes
        finally:
            primes_file.close()

    @property
    def bannerText(self):
        # TODO: We should really be getting this motd from the world instance
        return textwrap.dedent("""\
            HERE BE DRAGONS!
            This software is highly experimental. Try not to break it.
            Debug logging is enabled. DO NOT enter any real passwords - all input is logged!
            """)

    def buildProtocol(self, address):
        """
        Build an SSHServerTransport for this connection.

        :param address: A :class:`twisted.internet.interfaces.IAddress` provider, representing the IP address
            of the client connecting to us.
        :return: A :class:`SSHServerTransport` instance, or None if the connection should be rejected.
        """
        # Reject this connection if the IP is banned.
        if ip2int(address.host) in global_ban_list:
            logger.verbose("Rejecting connection from banned IP {0}".format(address.host))
            # This will send a RST packet
            return None
        # otherwise all good
        logger.verbose("Incoming SSH connection from {0}".format(address.host))

        # Let our superclass do the rest
        transport = conch_factory.SSHFactory.buildProtocol(self, address)

        # Fix for Twisted bug? supportedPublicKeys is a dict_keys object,
        # but Twisted tries to use it as a sequence. Convert it to a list.
        transport.supportedPublicKeys = list(transport.supportedPublicKeys)

        return transport

    @staticmethod
    def ban_host(host, duration=None):
        """
        Bans a host from connecting.
        """
        # TODO: Timed bans?
        logger.verbose("Banning IP {0}".format(host))
        global_ban_list.add(ip2int(host))


