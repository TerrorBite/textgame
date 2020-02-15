
from zope.interface import implements, implementer

from twisted.conch import recvline
from twisted.conch.insults import insults

import string

from textgame.interfaces import IUserProtocol
from textgame.Util import log, LogLevel, Loggable, get_logger

logger = get_logger(__name__)


@implementer(IUserProtocol)
class TermTransport(insults.ServerProtocol):
    """
    Provides a terminal-based UI as a user protocol.

    This class is both a user protocol and a terminal transport.
    """
    def __init__(self, user, width=80, height=24):
        insults.ServerProtocol.__init__(self, TextUI, user, width, height)
    
    def write_line(self, line): # Specified by IUserProtocol
        if self.terminalProtocol:
            self.terminalProtocol.write_line(line)

    def resize(self, width, height): # Specified by IUserProtocol
        if self.terminalProtocol:
            self.terminalProtocol.terminalSize(width, height)


class TextUI(recvline.HistoricRecvLine, Loggable):
    """
    A terminal protocol, with a separate editing area and display area.

    Presents a user interface for sending and receiving text.
    """

    logger = logger

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
        self._cpos_input(n % w, n // w)
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

    def lineReceived(self, line: bytes):
        line = line.decode("utf-8", errors="replace")
        log(LogLevel.Debug, "Received line: {0}".format(line))
        try:
            self.user.process_line(line)
        except Exception as e:
            self.logger.exception("Error while processing line")
            self.write_line("Server error while processing input, try something else?")
            self.write_line(f"  {type(e).__name__}: {e!s}")
            # self.terminal.loseConnection()
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
