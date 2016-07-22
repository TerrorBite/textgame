
from zope.interface import implements, Interface


from twisted.conch import avatar
from twisted.conch.interfaces import ISession
from twisted.conch.ssh import session
from twisted.conch.insults import insults

from Util import enum, log, LogLevel
import World, Things

State = enum('New', 'LoggedIn')

prelogincmds = []
commands = {}
class commandHandler:
    """
    Decorator that marks a method as a command handler.
    """
    def __init__(self, *aliases, **kwargs):
        self.cmds = aliases
        self.kwargs = kwargs
    def __call__(self, f):
        for cmd in self.cmds:
            commands[cmd] = f
        if 'prelogin' in self.kwargs and self.kwargs['prelogin']:
            for cmd in self.cmds:
                prelogincmds.append(cmd)

class commandHelpText:
    """
    Decorator that easily lets help text be specified on a command.
    """
    def __init__(self, *text):
        self.text = '\r\n'.join(text)
    def __call__(self, f):
        f.helptext = self.text
        return f

class IUserProtocol(Interface):
    def write_line(line):
        """
        Sends a complete line of text to the user.
        """
        pass # Interface method

    def resize(width, height):
        """
        Notify a terminal-based protocol of a change in window size.
        """
        pass # Interface method

class Prelogin(object):
    """
    Provides functionality for an unauthenticated user to authenticate and select a character.
    """
    # TODO: What is this for?

class User(object):
    """
    Represents a connected, online user, capable of running commands and receiving output.

    This class is responsible for parsing incoming text from a user, acting on commands, etc.
    """
    def __init__(self, username, transport=None):
        self.transport = transport
        self.username = username
        self.world = World.getWorld()
        self.state = State.New

    def send_message(self, msg):
        self.transport.write_line(msg.encode('utf8'))

    def run_command(self, msg):
        """
        Runs a command as this User's currently active character.
        """
        pass

    # Commands

    @commandHandler('i', 'inv', 'inventory')
    @commandHelpText("Prints a listing of what you are carrying.")
    def cmd_inv(self, params):
        """
        Built in inventory command. Prints a listing of what the character is carrying.
        """
        if self.my_state < State.LoggedIn:
            self.send_message("You're not connected to a character.")
            return
        self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name, self.player.contents))))

    @commandHandler('@create', 'create', prelogin=True)
    @commandHelpText("Creates a new character.")
    def cmd_create(self, params):
        """
        Creates a new character.
        """
        if self.my_state > State.New:
            self.send_message("You are already connected.")
            return
        _, user, passwd = line.split()
        # TODO: more code here
        return

    @commandHandler('@look', 'look')
    @commandHelpText("Describes the room that you're in, and tells you what other objects are around you.")
    def cmd_look(self, params):
        """
        Built in look command. Simply returns the output of Player.look()
        """
        if params:
            self.send_message(self.player.look(params[0]))
        else: 
            self.send_message(self.player.look())
        return

    @commandHandler('@debug')
    @commandHelpText("Debugging commands for admin use only.")
    def cmd_debug(self, params):
        """
        This command exists for debugging purposes and
        is restricted to the admin user.
        """
        if self.player.id != 1:
            self.send_message("You're not allowed to do that.")
            return
        if params:
            if params[0] == 'cache':
                self.world.purge_cache(10)

    @commandHandler('@quit', 'QUIT', prelogin=True)
    @commandHelpText("Disconnects you completely from the server.")
    def cmd_QUIT(self, params):
        """
        This command ends the user's connection after sending a goodbye message.
        It can be used when not logged in.
        The "QUIT" variant exists for legacy reasons.
        """
        self.send_message("Goodbye!")
        self.transport.loseConnection()
        return

    @commandHandler('@who', 'WHO', prelogin=True)
    @commandHelpText("Shows you who is online.")
    def cmd_WHO(self, params):
        """
        This command lists the currently online users.
        It can be used when not logged in.
        The "WHO" variant exists for legacy reasons.
        """
        # TODO: Track who's online
        self.send_message("Nobody else is connected.")
        return

    @commandHandler('@connect', 'connect', prelogin=True)
    @commandHelpText("Connects you to one of your characters.")
    def cmd_connect(self, params):
        """
        This command allows a user to log in as a particular character.
        This can be used when not logged in, but requires a password to do so.
        """
        log(LogLevel.Debug, "Received connect command from {0}".format(self.transport.getHost().host))
        if self.my_state > State.New:
            #Already connected
            self.send_message("You are already connected.")
            return
        if len(params) < 2:
            self.send_message("You must provide both a character name and a password.")
            return
        user = params[0]
        passwd = params[1]
        # Try and auth to an account
        self.player = self.world.connect(user, passwd)
        if self.player:
            self.complete_login()
        else:
            self.send_message("Your login failed. Try again.")
        return

    @commandHandler('@help', prelogin=True)
    @commandHelpText("Provides help on builtin commands.",
            "Usage: @help <command>")
    def cmd_help(self, params):
        """
        Builtin help command.
        """
        if len(params) < 1:
            self.send_message("Here is a listing of help topics:")
            self.send_message("TODO: Help")
            return
        keyword = params[0].lower()
        if keyword in commands.keys() and hasattr(commands[keyword], 'helptext'):
            self.send_message('Help for command "{0}":'.format(keyword))
            self.send_message(commands[keyword].helptext)
        else:
            self.send_message('There is no help available for "{0}".'.format(keyword))
        

    def complete_login(self):
        """
        This code is run when a character is successfully connected to.
        """
        self.my_state = State.LoggedIn
        log(LogLevel.Notice, "{0}#{1} connected from {2}".format(self.player.name, self.player.id, '<unknown>'))
        # Make them look around and check their inventory
        location = self.player.parent # Get room that the player is in
        self.send_message("Welcome, {0}! You are currently in: {1}\r\n{2}".format(self.player.name, location.name, location.get_desc_for(self.player)))
        self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name, self.player.contents))))
     
    def process_line(self, line):
        "Process input"

        if line == '': return
        words = line.split()
        cmd = words[0]
        params = words[1:] if len(words) > 1 else []

        # Are we logged in?
        if self.my_state < State.LoggedIn:
            # Only prelogin commands may be used
            if words[0] in prelogincmds:
                commands[words[0]](self, params)
            else:
                self.send_message("You're not connected to a character.")
            return

        # Code execution only proceeds beyond this point on a logged in character.
        # Check for common prefixes:

        # Builtin say command
        if line[0] == '"':
            # Echo back to the player
            self.send_message('You say, "{0}"'.format(line[1:]))
            # Send message to others who can hear it
            # TODO: Insert code here
            return
        # pose command
        if line[0] == ':':
            # Echo back to the player
            self.send_message('{0} {1}'.format(self.player.name, line[1:]))
            # Send message to others who can see it
            # TODO: Insert code here
            return
        if line[0] != '@':
            # TODO: try and activate the named action/exit
            thing = self.player
            while True:
                actions = filter(lambda x: x.type is Things.Action and x.name.lower().startswith(words[0].lower()), thing.contents)
                log(LogLevel.Trace, "{0} contains {1}, matching: {2}".format(thing, thing.contents, actions))
                if len(actions) > 1:
                    self.send_message("I don't know which one you mean!")
                    return
                elif len(actions) == 1:
                    a = actions[0]
                    if a.use(self.player):
                        self.send_message(actions[0]['_/succ'] or "You go {0}.".format(a.name))
                    else:
                        self.send_message(actions[0]['_/fail'] or "This exit leads nowhere.") 
                    return
                elif thing.id == 0:
                    # We ended up in room #0 and no action was found 
                    break
                else:
                    thing = thing.parent

        # Command dispatch map. Most commands should be accessed this way.
        if words[0] in commands.keys():
            try:
                log(LogLevel.Debug, "{0} running command: {1}{2}".format(
                    "{0}#{1}".format(self.player.name, self.player.id) if self.player else self.transport.getHost().host,
                    words[0], "({0})".format(', '.join(params) if (words[0] not in ('connect', '@connect')) else '[redacted]')
                    if params else ''))
            except TypeError, e:
                log(LogLevel.Trace, "words: {0}, params: {1}".format(repr(words), repr(params)))
                log(LogLevel.Trace, "Exception: {0}".format(repr(e)))
            commands[words[0]](self, params)
            return

        # If control fell through this far, then we have an unknown command/action
        self.send_message("I don't know what that means.")
        return


class SSHUser(avatar.ConchUser, User):
    implements(ISession)
    
    def __init__(self, username):
        self.savedSize = ()
        avatar.ConchUser.__init__(self) # don't change to super(), it will break
        User.__init__(self, username)
        # what does the following do?
        self.channelLookup.update({'session':session.SSHSession})

    def openShell(self, trans):
        """
        Called when a shell is opened by a user logging in via SSH or similar.
        """
        # Create an SSHProtocol object and connect it
        from Network import SSHServerProtocol
        #self.transport = t = insults.ServerProtocol(SSHProtocol, self, *self.savedSize)
        self.transport = t = SSHServerProtocol(self, *self.savedSize)
        t.makeConnection(trans)
        trans.makeConnection(session.wrapProtocol(t))
        #self.send_message("Hi there!")
        self.player = self.world.get_thing(self.world.db.get_player_id(self.username))
        self.complete_login()

    def getPty(self, term, windowSize, modes):
        if not self.transport:
            self.savedSize = windowSize[1::-1]
        else:
            self.windowChanged(windowSize)
    
    def execCommand(self, proto, cmd):
        raise NotImplementedError()

    def closed(self):
        pass

    def eofReceived(self):
        pass

    def windowChanged(self, newSize):
        self.transport.resize(newSize[1], newSize[0])
