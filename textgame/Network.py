import enum
import socket
import struct
import textwrap
import threading
import time
import warnings
import weakref
from collections import defaultdict
from typing import List, Tuple, Dict

import twisted.conch.ssh.transport
import typing
from twisted.python import failure
from zope.interface import implementer

from twisted.internet import protocol, error
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


class CleanSSHServerTransport(twisted.conch.ssh.transport.SSHServerTransport):

    @property
    def peer(self) -> str:
        """Peer address as a string."""
        return "{0.host}:{0.port}".format(self.transport.getPeer())

    def connectionLost(self, reason=twisted.internet.protocol.connectionDone):
        self.connected = 0

        if self.service:
            # There is a service running, stop it.
            self.service.serviceStopped()

        if hasattr(self, "avatar"):
            # There is an avatar connected, call the logout function.
            self.logoutFunction()

        why = "aborted" if reason.check(twisted.internet.error.ConnectionAborted) else "lost"
        logger.verbose("Connection from %s was %s", self.peer, why)
        logger.trace("Connection from %s was lost because: %s", self.peer, reason.getErrorMessage())


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


class SSHWatchdog:
    """
    Connection watchdog. The purpose of the SSHWatchdog is to terminate connections that are invalid. In particluar,
    it terminates the following connections:

    * Connections that have been open for longer than 5 seconds, but have not completed an SSH handshake and started
      an SSH service, will be reset.
    * Connections that have been open for longer than 2 minutes but have not completed SSH authentication will be sent
      an SSH disconnect message. If they do not disconnect within five seconds, the connection will be reset.
    * TODO: Connections from the same IP that are in excess of the connection limit will be sent a disconnect
            message and then closed.
    """

    # Connections older than this which have not yet started authentication will be terminated.
    PREAUTH_TIMEOUT = 5

    # Connections older than this which have not yet completed authentication will be terminated.
    AUTH_TIMEOUT = 120

    class Action(enum.Enum):
        # Take no action.
        NONE = enum.auto()
        # Drop the connection from watchdog monitoring.
        DROP = enum.auto()
        # Abort the connection (and drop it from monitoring).
        ABORT = enum.auto()

    # Set up the Failure that will be raised in order to abort a connection
    connectionAborted = failure.Failure(error.ConnectionAborted())
    connectionAborted.cleanFailure()

    from twisted.internet import reactor

    if typing.TYPE_CHECKING:
        from twisted.internet import base as reactor_base
        reactor = typing.cast(reactor_base.ReactorBase, reactor)

    def __init__(self):
        self._watchdog_thread = threading.Thread(target=self._thread_main)
        self._watchdog_flag = threading.Event()

        # Dict of connections that have not completed the SSH auth service. These will be subject to the watchdog.
        self._unauth_connections = weakref.WeakKeyDictionary()

    def _check_conn(self, conn: twisted.conch.ssh.transport.SSHServerTransport, start_time) -> Action:
        """
        Check a connection object.

        :param conn: The connection object.
        :return: Pair of booleans: whether to drop from the set or to abort the connection.
        """

        peer = "{0.host}:{0.port}".format(conn.transport.getPeer())
        try:
            age = time.time() - start_time
            if not conn.connected:
                return self.Action.DROP

            if conn.service:
                authing = isinstance(conn.service, UserAuthService)
                if authing:
                    if age > self.AUTH_TIMEOUT:
                        # 2 minutes elapsed, but still in auth. Send SSH disconnect.
                        conn.sendDisconnect(
                            twisted.conch.ssh.transport.DISCONNECT_CONNECTION_LOST, "Authentication Timeout")
                        return self.Action.NONE
                    elif age > self.AUTH_TIMEOUT + self.PREAUTH_TIMEOUT:
                        # Already tried to disconnect this client but it is not listening
                        logger.verbose("SSH Watchdog: Client not responding to disconnect, aborting %s", peer)
                        return self.Action.ABORT
                else:
                    # Progressed beyond auth
                    logger.trace(
                        "SSH Watchdog: Connection from %s progressed beyond auth to %r, no need to keep watching it",
                        peer, conn.service)
                    return self.Action.DROP
            elif age > self.PREAUTH_TIMEOUT:
                # 5 seconds elapsed but no SSH connection. Drop the connection.
                logger.verbose("SSH Watchdog: Timeout, aborting %s", peer)
                return self.Action.ABORT
        except Exception:
            logger.exception("SSH Watchdog: Error handling connection %r", conn)

        return self.Action.NONE

    def _thread_main(self):
        """Thread body."""

        logger.debug("SSH Watchdog: Thread started")
        while not self._watchdog_flag.wait(1.00):

            conn: twisted.conch.ssh.transport.SSHServerTransport

            actions = [(conn, self._check_conn(conn, start)) for conn, start in self._unauth_connections.items()]

            to_abort = {conn for conn, action in actions if action == self.Action.ABORT}
            to_drop = {conn for conn, action in actions if action == self.Action.DROP}

            if to_abort:
                # Twisted is a single-threaded framework - multiple connections are multiplexed - and it freaks out
                # if we close the socket from a thread while the reactor is waiting on the socket. To handle this
                # correctly, we need the main thread running the Twisted Reactor to close the socket, while it is not
                # waiting on the socket. To achieve this, we can wake the reactor and have it run our code.
                # This is accomplished using reactor.callFromThread() which is a method designed specifically for
                # other threads to use.
                logger.trace("SSH Watchdog: Will abort %d connections", len(to_abort))
                # Call abort_many() with to_abort as argument
                self.reactor.callFromThread(self.abort_many, to_abort)

            for conn in (to_abort | to_drop):
                now = time.time()
                age = now - self._unauth_connections.get(conn, now)
                logger.trace("SSH Watchdog: No longer monitoring %r, age %.2fs", conn, age)
                if self._unauth_connections.pop(conn, None) is None:
                    logger.warning("SSH Watchdog: Connection %r is not known by watchdog", conn)

        logger.debug("SSH Watchdog: Thread is exiting")

    def add(self, conn: twisted.conch.ssh.transport.SSHServerTransport):
        """
        Add a connection to be monitored by the watchdog.
        """
        self._unauth_connections[conn] = time.time()

    def remove(self, conn: twisted.conch.ssh.transport.SSHServerTransport):
        """
        Remove a connection to be monitored by the watchdog.
        """
        self._unauth_connections.pop(conn, None)

    def abort(self, conn: twisted.conch.ssh.transport.SSHServerTransport):
        """Aborts the given connection."""
        conn.transport.connectionLost(self.connectionAborted)

    def abort_many(self, connections: typing.Iterable[twisted.conch.ssh.transport.SSHServerTransport]):
        """Aborts the given connections."""
        for conn in connections:
            conn.transport.connectionLost(self.connectionAborted)

    def start(self):
        """Starts the watchdog thread."""
        self._watchdog_thread.start()

    def stop(self):
        """Shuts down the watchdog thread."""
        self._watchdog_flag.set()


class HostBan:
    """
    Represents a ban against a host.

    Two different types of ban can be applied, both having different effects:
    * A soft ban results in a "Host Not Allowed" disconnection message and a clean close of the connection.
    * A hard ban results in the connection being reset after being accepted, with no data sent at all.

    :param host: The IP address or CIDR that is banned.
    :param hard: Boolean, True if the host is hard-banned (see above).
    :param expiry: An integer timestamp of expiry, or None if this ban does not expire.
    """
    def __init__(self, host: str, hard: bool, expiry: typing.Optional[int] = None):
        self.host: str = host
        self.hard: bool = hard
        self.expiry: typing.Optional[int] = expiry

    @property
    def expired(self):
        return self.expiry is not None and self.expiry < time.time()


class BanManager:

    def __init__(self):
        self.bans: typing.Dict[str, HostBan] = {}

    def get(self, ip_addr: str) -> typing.Optional[HostBan]:
        """Gets whether the host is banned."""
        ban = self.bans.get(ip_addr, None)
        if ban is None:
            return None
        if ban.expired:
            del self.bans[ip_addr]
            return None
        return ban

    def add(self, ip_addr: str, hard: bool = True):
        self.bans[ip_addr] = HostBan(ip_addr, hard)

    def add_temp(self, ip_addr: str, expiry: int, hard: bool = True):
        self.bans[ip_addr] = HostBan(ip_addr, hard, expiry)


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

        self.ip_bans = BanManager()

        self.watchdog = SSHWatchdog()

    services = {
        b'ssh-userauth': UserAuthService,
        # b'ssh-connection': connection.SSHConnection
        b'ssh-connection': SSHShellOnlyConnection
    }

    protocol = CleanSSHServerTransport

    def getPublicKeys(self) -> Dict[bytes, keys.Key]:
        return {
            b'ssh-rsa': self._rsa_pub
        }

    def getPrivateKeys(self) -> Dict[bytes, keys.Key]:
        return {
            b'ssh-rsa': self._rsa_key
        }

    primes_path = '/etc/ssh/moduli'

    def startFactory(self):
        """
        Called when the factory is starting up.

        Starts the watchdog thread.
        """
        self.watchdog.start()
        super().startFactory()

    def stopFactory(self):
        """
        Called when the factory is being shut down.

        Ends the watchdog thread.
        """
        self.watchdog.stop()
        super().stopFactory()

    def getPrimes(self):
        """
        Return dictionary with primes number.
        Reads prime numbers from OpenSSH compatible moduli file.
        """
        try:
            primes_file = open(self.primes_path, 'r')
        except FileNotFoundError:
            logger.warning(f"Unable to open moduli file '{self.primes_path}'. This will reduce the number of"
                           f"available key exchange algorithms, and may affect compatibility.")
            return {}

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
        ban = self.ip_bans.get(address.host)
        if ban and ban.hard:
            logger.verbose("Rejecting connection from banned IP {0}".format(address.host))
            # This will send a RST packet
            return None
        # otherwise all good
        logger.verbose("Incoming SSH connection from {0.host}:{0.port}".format(address))

        # Let our superclass do the rest
        transport = conch_factory.SSHFactory.buildProtocol(self, address)

        if ban:
            def disconnect():
                transport.sendDisconnect(1, "You are banned from this server.")
            transport.sendKexInit = disconnect
            return transport

        # Register the transport for the watchdog
        self.watchdog.add(transport)

        # Fix for Twisted bug? supportedPublicKeys is a dict_keys object,
        # but Twisted tries to use it as a sequence. Convert it to a list.
        transport.supportedPublicKeys = list(transport.supportedPublicKeys)

        return transport

    def ban_host(self, host, hard=False, duration=None):
        """
        Bans a host from connecting.
        """
        # TODO: Timed bans?
        logger.verbose("Banning IP {0}".format(host))
        self.ip_bans.add(host, hard)
