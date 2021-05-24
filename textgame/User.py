import logging
from enum import Enum

from twisted.conch import avatar
from twisted.conch.interfaces import ISession
from twisted.conch.ssh import session
from zope.interface import implementer

from textgame import Things
from textgame.Terminal import TermTransport
from textgame.Util import get_logger

ADMINISTRATIVELY_PROHIBITED = 1

logger = get_logger(__name__)


class State(Enum):
    New = 0
    Logged_In = 1


prelogincmds = []
commands = {}


# noinspection PyPep8Naming
class commandHandler(object): # Decorator
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

class commandHelpText(object): # Decorator
    """
    Decorator that easily lets help text be specified on a command.
    """
    def __init__(self, *text):
        self.text = '\r\n'.join(text)
    def __call__(self, f):
        f.helptext = self.text
        return f


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
    def __init__(self, world, username, transport=None):
        # Transport
        self.transport = transport
        # The username of the connected user.
        self.username = username
        # The world which the user is joining.
        self.world = world
        # The user begins in the New state.
        self.state = State.New

    def send_message(self, msg):
        """
        Sends a line of text to the user, using the underlying transport.
        """
        self.transport.write_line(msg.encode('utf8'))

    def run_command(self, msg):
        """
        Runs a command as this User's currently active character.

        This method is intended to allow another object (or player) to "force" this player to do something, like a puppet. 
        """
        #TODO: Implement User.run_command()
        # How should this differ from process_line()? What constitutes a "command"?
        # Should this disallow @-commands or allow only actions?
        self.process_line(msg) # just do this for now

    # Commands

    @commandHandler('i', 'inv', 'inventory')
    @commandHelpText("Prints a listing of what you are carrying.")
    def cmd_inv(self, params):
        """
        Built in inventory command. Prints a listing of what the character is carrying.
        """
        if self.my_state.value < State.Logged_In.value:
            self.send_message("You're not connected to a character.")
            return
        self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name, self.player.contents))))

    @commandHandler('@create', 'create', prelogin=True)
    @commandHelpText("Creates a new character.")
    def cmd_create(self, params):
        """
        Creates a new character.
        """
        if self.my_state.value > State.New.value:
            self.send_message("You are already connected.")
            return
        # _, user, passwd = line.split()
        # TODO: Deprecate this method.
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
        This command exists for debugging purposes and is restricted to the admin user.

        Various sub-commands may exist depending on the needs of a developer.
        """
        if self.player.id != 1:
            self.send_message("You're not allowed to do that.")
            return
        if params:
            if params[0] == 'cache':
                self.world.purge_cache(10)

    @commandHandler('@save')
    @commandHelpText("Allows admins to immediately save the world to the database.")
    def cmd_save(self, params):
        """
        This command saves the database immediately.
        """
        if self.player.id != 1:
            self.send_message("You're not allowed to do that.")
            return
        self.world.purge_cache(-1)

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

    @commandHandler('@name')
    def cmd_name(self, params):
        if len(params) == 0:
            return
        param = ' '.join(params)
        if '=' not in param: return
        target, name = param.split('=', 1)
        target = self.player.find(target)
        if target is None:
            self.send_message("Can't find that.")
            return
        target.name = name

    @commandHandler('@connect', 'connect', prelogin=True)
    @commandHelpText("Connects you to one of your characters.")
    def cmd_connect(self, params):
        """
        This command allows a user to log in as a particular character.
        This can be used when not logged in, but requires a password to do so.
        """
        logger.debug("Received connect command from %s", self.transport.getHost().host)
        #log(LogLevel.Debug, "Received connect command from {0}".format(self.transport.getHost().host))
        if self.my_state > State.New.value:
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

    def create_character(self, charname):
        """
        Creates a new character for this User.
        """
        return self.world.db.create_character(self.username, charname)

    def complete_login(self):
        """
        This code is run after a character is successfully connected to.

        When this function is called, the self.player object should already
        be initialized.
        """
        self.my_state = State.Logged_In
        logger.info("%s#%s has awoken", self.player.name, self.player.id)
        self.send_message("To disconnect, type @quit")
        # Make them look around and check their inventory
        location = self.player.parent # Get room that the player is in
        self.send_message("Welcome, {0}! You are currently in: {1}\r\n{2}".format(self.player.name, location.name, location.get_desc_for(self.player)))
        self.send_message("You are carrying: {0}".format(', '.join(map(lambda x: x.name, self.player.contents))))
     
    def process_line(self, line):
        """
        Processes a line of input from the user.
        """

        if line == '': return
        words = line.split()
        cmd = words[0]
        params = words[1:] if len(words) > 1 else []

        # Are we logged in?
        if self.my_state.value < State.Logged_In.value:
            # Only prelogin commands may be used
            if words[0] in prelogincmds:
                commands[words[0]](self, params)
            else:
                self.send_message("You're not connected to a character.")
            return

        # Code execution only proceeds beyond this point on a logged in character.
        # Commands are checked in the following order:
        # 1. Special prefixes (including @commands and the "say and :pose builtins)
        # 2. Matching actions (in order: player, room, objects in room, and then parent rooms)
        # 3. Builtin commands that do not have a special prefix

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

        # If input begins with @, skip looking for actions (an action should never
        # begin with a @ character). Otherwise...
        if line[0] != '@':
            # Start the search at the player
            thing = self.player
            while True:
                logger.trace("Searching %s for %s", thing.name, words[0])
                # Retrieve a list of Actions contained by this thing, which match the word entered
                actions = [
                    x for x in thing.contents
                    if x.type is Things.Action and x.name.lower().startswith(words[0].lower())
                ]
                logger.trace("%r contains %r, matching: %r", thing, thing.contents, actions)

                # Process list, and return if actions were found
                if self.process_action_list(actions):
                    return

                logger.trace("Searching %s's contents for %s", thing.name, words[0])

                # Retrieve a list of Items contained by this thing, and look for Actions on them.
                # This is to locate items that are carried by the player, or that are contained in
                # the same room as the player, or contained in a parent room of the player's room.
                actions = set()

                # For each Item that the target thing contains:
                for item in filter(lambda i: i.type is Things.Item, thing.contents):
                    # For each Action on that Item:
                    for action in filter(lambda a: a.type is Things.Action, item.contents):
                        # If the name matches:
                        if action.name.lower().startswith(words[0].lower()):
                            # Then add it to the set
                            actions.add(action)
                logger.trace("%r's contents contain matching: %r", thing, actions)

                # Process list, and return if actions were found
                if self.process_action_list(actions):
                    return

                # Move to this Thing's parent and keep searching, unless we reached Room #0
                # in which case we are at the root of the parent tree and we give up.
                if thing.id == 0:
                    break
                else:
                    thing = thing.parent

        # Command dispatch map. Built-in commands should be accessed this way.
        if words[0] in commands.keys():
            try:
                if logger.isEnabledFor(logging.DEBUG):
                    # Prepare some data for logging
                    who_f = f"{self.player.name}#{self.player.id}" if self.player else self.transport.getHost().host
                    params_f = f"({', '.join(params)})" if params else ''

                    if words[0] in ('connect', '@connect'):
                        # Parameter is a password, and must be redacted
                        params_f = "[password redacted]"

                    logger.debug(f"{who_f} running command: {words[0]}{params_f}")

            except TypeError:
                logger.trace(f"words: {words!r}, params: {params!r}", exc_info=True)

            # Execute the command
            commands[words[0]](self, params)
            return

        # If control fell through this far, then we have an unknown command/action
        self.send_message("I don't know what that means.")
        return

    def process_action_list(self, actions):
        if len(actions) > 1:
            # Too many actions
            self.send_message("I don't know which one you mean!")
        elif len(actions) == 1:
            # Only one thing matches. This must be it.
            a = actions[0]
            # Use the Action as ourselves, check for success
            # TODO: need to send the message BEFORE the Action has any other side effects
            if a.use(self.player):
                self.send_message(actions[0]['_/succ'] or "You go {0}.".format(a.name))
            else:
                self.send_message(actions[0]['_/fail'] or "This exit leads nowhere.")
        else:
            # No actions found
            return False
        
        return True  # Found a match


@implementer(ISession)
class SSHUser(avatar.ConchUser, User):
    """
    This is an adaptor on top of the User class which makes it available
    as an SSH server session. The primary purpose of this class is to connect the
    SSH transport to our Protocol which travels over that transport.

    Our Protocol is a protocol in the general sense, not the networking sense; it is
    interfacing with a human rather than client software, so it's actually presenting
    a text-based user interface across the transport.
    """

    def __init__(self, world, username):
        self.savedSize = ()
        # Initialize our superclasses.
        # Don't change these to use super(), it will break
        avatar.ConchUser.__init__(self)
        User.__init__(self, world, username)
        # what does the following do?
        self.channelLookup.update({
            b'session': session.SSHSession,
        })

    def lookupChannel(self, channelType, windowSize, maxPacket, data):
        logger.debug(f"Channel type is: {channelType}")
        return super().lookupChannel(channelType, windowSize, maxPacket, data)

    def select_character(self, charname):
        """
        Sets the character name which this SSHUser will access.
        """
        chars = self.character_names
        logger.debug(f"User {self.username} has the following characters: {', '.join(chars)}")
        if charname.lower() in [c.lower() for c in chars]:
            self._charname = charname
            logger.debug(f"Selected {self._charname} on {self!r}")
            return True
        else:
            # Requested character name not found
            return False

    @property
    def character_names(self):
        return self.world.db.get_user_characters(self.username)

    def openShell(self, ssh_channel):
        """
        Called when a shell is opened by a user logging in via SSH or similar.

        Wea are provided with a transport which is the open SSH
        channel we will use to send and receive.
        """
        # Obtain a protocol instance. This is our custom Network.SSHServerProtocol.
        # The protocol controls the way that data is sent and received down the connection.
        # In our case, it presents a TTY-based user interface to the user, while all we care
        # about is sending lines to the user and receiving lines from them.
        #TODO: Why isn't this import at the top?
        #from Network import SSHServerProtocol
        # Get the protocol instance. The protocol is also our transport.
        #     Note that the Twisted networking model is a stack of protocols,
        #     where lower level protocols transport higher level ones.

        # The underlying transport of this User session will be a
        # text UI which itself uses an SSH channel as its transport.
        self.transport = TermTransport(self, *self.savedSize)
        
        # Connect the text UI to its transport.
        self.transport.makeConnection(ssh_channel)

        # Still don't understand why the reverse connection
        ssh_channel.makeConnection(session.wrapProtocol(self.transport))

        # Obtain the Player object from the database
        logger.debug(f"Getting Player for {self!r}")
        player_id = self.world.db.get_player_id(self.username, self._charname)
        logger.debug("Username: {0}, character: {2}, id: {1}".format(self.username, player_id, self._charname))

        self.player = self.world.get_thing(player_id)

        # Finish login. This calls the method in the User class which sends
        # the initial greeting, etc.
        self.complete_login()

    def getPty(self, term, windowSize, modes):
        """
        TODO: describe this method
        """
        if not self.transport:
            self.savedSize = windowSize[1::-1]
        else:
            self.windowChanged(windowSize)
    
    def execCommand(self, proto: session.SSHSessionProcessProtocol, cmd):
        """
        This method would be called when an attempt is made to run a single
        command via SSH rather than establishing an interactive session.

        We don't support this, so we close the connection.
        """
        logger.debug(f"\n{repr(proto)}\n{dir(proto)}")
        proto.write("Your SSH client requested to execute a command. This is not supported.\n")
        logger.debug(f"Attempt to execute command: {cmd!r}")
        proto.transport = DummyTransport()
        proto.processEnded()

    def closed(self):
        """
        This method is called when the connection is closed (? Verify this)
        """
        pass

    def eofReceived(self):
        """
        This method is called when the end of input is received. Basically
        if the user has gone away somehow. (?Verify this)
        """
        pass

    def windowChanged(self, newSize):
        """
        Called in the case where the user has resized their SSH window.
        When this happens, we need to tell our protocol so that it can
        re-render its text-based interface at the new size.
        """
        self.transport.resize(newSize[1], newSize[0])


class DummyTransport:

    def loseConnection(self):
        pass
