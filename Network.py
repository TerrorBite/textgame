from zope.interface import implements
from twisted.conch.interfaces import IConchUser

from twisted.internet import protocol
from twisted.cred import portal
from twisted.conch import avatar, recvline
from twisted.conch.insults import insults
from twisted.conch.ssh import factory as conch_factory, userauth, connection, keys, session
from twisted.conch.ssh.address import SSHTransportAddress

from Util import log, LogLevel, enum

import string

import World
import Things
from User import SSHUser, IUserProtocol, State

class BareUserProtocol(protocol.Protocol):
    implements(IUserProtocol)
    """
    Processes a basic user session - a raw connection with no UI presented to the user.
    """

    # TODO: This code needs to be completely rewritten.

    def __init__(self, user=None):
        self.user = user
        self.buf = ''

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





class SSHRealm:
    """
    This simple realm generates User instances.

    This is basically a factory for SSHUser instances. After SSH authentication
    has succeeded, the SSHRealm is provided with the username of the account that
    just logged in, and uses it to create and return an appropriate User instance.
    """
    implements(portal.IRealm)

    def __init__(self, world):
        self.world = world

    def requestAvatar(self, avatarId, mind, *interfaces):
        if IConchUser in interfaces:
            return interfaces[0], SSHUser(self.world, avatarId), lambda: None
        else:
            log(LogLevel.Error, "SSHRealm: No supported interfaces")
            raise NotImplementedError("No supported interfaces found.")


def SSHFactoryFactory(world):
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

    import Database
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
        # This Portal tells us how to authenticate users.
        # The SSHRealm will generate user instances after auth succeeds.
        # The Database.CredentialsChecker can verify a username and password
        # pair against the database.
        portal = Portal(SSHRealm(world), [Database.CredentialsCecker(world.db)])

    return SSHFactory()
    # End of SSH host key loading code

class UserAuthService(userauth.SSHUserAuthServer):
    def serviceStarted(self):
        #need keyboard-interactive interface to exist
        self.interfaceToMethod[iface] = u'keyboard-interactive'
        userauth.SSHUserAuthServer.serviceStarted(self)

@implementer(IUserProtocol)
class SSHServerProtocol(insults.ServerProtocol):
    """
    A terminal transport, which supports our custom terminal protocol.
    """
    def __init__(self, user, width=80, height=24):
        insults.ServerProtocol.__init__(self, SSHProtocol, user, width, height)
    
    def write_line(self, line): # Specified by IUserProtocol
        if self.terminalProtocol:
            self.terminalProtocol.write_line(line)

    def resize(self, width, height): # Specified by IUserProtocol
        if self.terminalProtocol:
            self.terminalProtocol.terminalSize(width, height)


class SSHProtocol(recvline.HistoricRecvLine):
    """
    A terminal protocol, with a separate editing area and display area.

    Presents a user interface for sending and receiving text.
    """

    def __init__(self, user=None, width=80, height=24):
        recvline.HistoricRecvLine.__init__(self)
        self.scrollback = []
        self.user = user
        self.width = width
        self.height = height

    # Override methods

    def connectionMade(self):
        recvline.HistoricRecvLine.connectionMade(self)
        self.keyHandlers['\x08'] = self.handle_BACKSPACE # Make ^H work like ^?
        self.keyHandlers['\x15'] = self.handle_CTRL_U # Make ^U clear the input
        self.keyHandlers['\x01'] = self.handle_HOME   # Make ^A work like Home
        self.keyHandlers['\x05'] = self.handle_END    # Make ^E work like End
        self.keyHandlers['\x0c'] = self.handle_CTRL_L # Redraws the screen
        #self.write_line("Debug: SSHProtocol welcomes you")

    def initializeScreen(self):
        self.terminal.reset()
        self.redraw()
        self.setInsertMode()

    def terminalSize(self, width, height):
        """
        This method is called when the terminal size changes.
        """
        self.width = width
        self.height = height
        self.redraw()

    def handle_UP(self):
        if self.lineBuffer and self.historyPosition == len(self.historyLines):
            # append entered line onto history
            self.historyLines.append(self.lineBuffer)
        if self.historyPosition > 0:
            self.reset_input()
            self.historyPosition -= 1
            self._deliverBuffer(self.historyLines[self.historyPosition])

    def handle_DOWN(self):
        if self.historyPosition < len(self.historyLines):
            self.reset_input()
            self.historyPosition += 1
            if self.historyPosition < len(self.historyLines):
                self._deliverBuffer(self.historyLines[self.historyPosition])

    def handle_HOME(self):
        """
        Handles the HOME key or equivalent.
        Moves cursor and insertion point to the start of input.
        """
        self._cpos_input(len(self.ps[self.pn]))
        #self.show_prompt()
        self.lineBufferIndex = 0

    def handle_END(self):
        """
        Handles the END key or equivalent.
        Moves cursor and insertion point to the end of input.
        """
        n = len(self.lineBuffer) + len(self.ps[self.pn])
        w = self.width
        self._cpos_input(n%w, n/w)
        self.lineBufferIndex = len(self.lineBuffer)

    #def keystrokeReceived(self, keyID, modifier):
        # XXX Debug only please remove
        #log(LogLevel.Trace, 'Keypress: {0}'.format(repr(keyID)))
        #recvline.HistoricRecvLine.keystrokeReceived(self, keyID, modifier)

    # Unique methods
    def handle_CTRL_L(self):
        """Standard "redraw screen" keypress"""
        self.redraw()

    def handle_CTRL_U(self):
        """Standard "clear line" keypress"""
        self.reset_input()

    def reset_input(self):
        self._cpos_input()
        self.terminal.eraseToDisplayEnd()
        self.show_prompt()
        self.lineBuffer = []
        self.lineBufferIndex = 0

    def show_prompt(self):
        self.terminal.write(self.ps[self.pn])

    def lineReceived(self, line):
        log(LogLevel.Debug, "Received line: {0}".format(line))
        try:
            self.user.process_line(line)
        except Exception as ex:
            from traceback import print_exc
            print_exc(ex)
            self.write_line("Suddenly the dungeon collapses!! You die... (Server error)")
            self.terminal.loseConnection()
        self._cpos_input()
        self.terminal.eraseToDisplayEnd()
        self.drawInputLine()

    def write_line(self, line):
        """
        Writes a line to the screen on the line above the input line,
        pushing existing lines upwards.
        """
        if len(self.scrollback) > 500:
            self.scrollback.pop(0)
        self.scrollback.append(line)

        self.terminal.saveCursor()
        self.terminal.setScrollRegion(0, self.height - 4)

        self._cpos_print()
        self.terminal.nextLine()
        self.terminal.write(line)

        self.terminal.setScrollRegion(self.height - 2, self.height)
        self.terminal.restoreCursor()

    def restore_scrollback(self):
        """
        Redraws scrollback onto the screen.
        """
        self._cpos_print()
        for line in self.scrollback[-self.height:]:
            self.terminal.nextLine()
            self.terminal.write(line)

    def redraw(self):
        """
        Redraws the screen, restoring scrollback and current input line.
        Should be used when screen size changes.
        """
        self.terminal.eraseDisplay()
        self.terminal.setScrollRegion(0, self.height - 4)
        self.restore_scrollback()
        self.terminal.cursorPosition(0, self.height - 4)
        self.terminal.write('='*self.width)
        self.terminal.setScrollRegion(self.height - 2, self.height)
        self._cpos_input() # should work regardless of auto-margins
        self.drawInputLine()

    def _cpos_input(self, offset=0, line_offset=0):
        """
        Positions the cursor at the input position.
        """
        self.terminal.cursorPosition(offset, self.height + line_offset - 3)

    def _cpos_print(self):
        """
        Positions the cursor at the output (print) position.
        """
        self.terminal.cursorPosition(0, self.height - 5)
