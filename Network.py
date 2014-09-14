from twisted.internet import protocol
from Util import log, LogLevel, enum

import World
import Things

State = enum('New', 'LoggedIn')

commands = {}
class commandHandler:
    def __init__(self, *aliases):
        self.cmds = aliases
    def __call__(self, f):
        for cmd in self.cmds:
            commands[cmd] = f


class UserSession(protocol.Protocol):

    def __init__(self):
        self.world = World.getWorld()
        self.player = None
        self.my_state = State.New
        self.buf = ''

    def connectionMade(self):
        log(LogLevel.Info, "Incoming connection from {0}".format(self.transport.getHost()))
        self.host = self.transport.getHost().host

    def connectionLost(self, data):
        log(LogLevel.Info, "{0}#{1} [{2}] lost connection: {3}".format(self.player.name(), self.player.id(), self.host, data.getErrorMessage()))

    def dataReceived(self, data):
        "When data is received, process it according to state."
        if '\n' in data:
            # Strip CR
            data = data.translate(None, '\r')
            # Split to completed lines
            lines = data.split('\n')
            lines[0] = self.buf+lines[0]
            self.buf = lines[-1]
            for line in lines[:-1]: self.process_line(line.strip())
        else:
            log(LogLevel.Debug, "Received data without terminating newline, buffering")
            self.buf += data

    def send_message(self, msg):
        self.transport.write(msg.encode('utf8')+'\r\n')

    @commandHandler('@debug')
    def cmd_debug(self, params):
        if params:
            if params[0] == 'cache':
                self.world.purge_cache(10)

    @commandHandler('@quit', 'QUIT')
    def cmd_QUIT(self, params):
        self.send_message("Goodbye!")
        self.transport.loseConnection()
        return

    @commandHandler('@who', 'WHO')
    def cmd_WHO(self, params):
        # TODO: Track who's online
        self.send_message("Nobody else is connected.")
        return

    @commandHandler('connect')
    def cmd_connect(self, params):
        log(LogLevel.Debug, "Received connect command from {0}".format(self.transport.getHost()))
        if self.my_state > State.New:
            #Already connected
            self.send_message("You are already connected.")
            return
        user = params[0]
        passwd = params[1]
        # Try and auth to an account
        self.player = self.world.connect(user, passwd)
        if self.player:
            self.my_state = State.LoggedIn
            log(LogLevel.Notice, "{0}#{1} connected from {2}".format(self.player.name(), self.player.id(), self.transport.getHost().host))
            # Make them look around and check their inventory
            location = self.player.parent() # Get room that the player is in
            self.send_message("Welcome, {0}! You are currently in: {1}\r\n{2}".format(self.player.name(), location.name(), location.desc(self.player)))
            self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name(), self.player.contents()))))
            
        else:
            self.send_message("Your login failed. Try again.")
        return

    @commandHandler('@i', '@inv', '@inventory')
    def cmd_inv(self, params):
        if self.my_state < State.LoggedIn:
            self.send_message("You're not connected to a character.")
            return
        self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name(), self.player.contents()))))

    @commandHandler('@create', 'create')
    def cmd_create(self, params):
        if self.my_state > State.New:
            self.send_message("You are already connected.")
            return
        _, user, passwd = line.split()
        # TODO: more code here
        return


    def process_line(self, line):
        "Process input"

        if line == '': return
        words = line.split()
        cmd = words[0]
        params = words[1:] if len(words) > 1 else None

        # Command dispatch map. Most commands should be accessed this way.
        if words[0] in commands.keys():
            try:
                log(LogLevel.Debug, "{0} running command: {1}{2}".format(
                    "{0}#{1}".format(self.player.name(), self.player.id()) if self.player else self.transport.getHost().host,
                    words[0], "({0})".format(', '.join(params) if (words[0] not in ('connect', '@connect')) else '[redacted]')
                    if params else ''))
            except TypeError, e:
                log(LogLevel.Trace, "words: {0}, params: {1}".format(repr(words), repr(params)))
                log(LogLevel.Trace, "Exception: {0}".format(repr(e)))
            commands[words[0]](self, params)
            return

        # Everything following this point can only be run on a logged in character.
        if self.my_state < State.LoggedIn:
            self.send_message("You're not connected to a character.")
            return
        # Check for common prefixes:

        # say command
        if line[0] == '"':
            # Echo back to the player
            self.send_message('You say, "{0}"'.format(line[1:]))
            # Send message to others who can hear it
            # TODO: Insert code here
            return
        # pose command
        if line[0] == ':':
            # Echo back to the player
            self.send_message('{0} {1}'.format(self.player.name(), line[1:]))
            # Send message to others who can see it
            # TODO: Insert code here
            return
        if line[0] == '@':
            self.at_command(words[0], params)
            return


        # TODO: try and activate the named action/exit

        # Other basic commands
        if line.lower().startswith('look'):
            params = line.split(None, 1)
            if len(params) > 1:
                self.send_message(self.player.look(params[1]))
            else: 
                self.send_message(self.player.look())
        return

        # If control fell through this far, then we have an unknown command/action
        self.send_message("I don't know what that means.")
        return

    def at_command(self, command, params):

        # Placeholder
        self.send_message("You ran command: @{0}\r\nWith params: {1}".format(command, params))


        if command=="dig":
            room = Things.Room()
        

        return
