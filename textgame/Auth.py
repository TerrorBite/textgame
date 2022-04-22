# Twisted imports
from collections import Awaitable
from enum import Enum, IntEnum
from typing import NamedTuple, List, Optional, Sequence, TYPE_CHECKING

import twisted.cred.error
from twisted.conch import error
from twisted.conch.ssh.service import SSHService
from twisted.conch.ssh.userauth import SSHUserAuthServer
from zope.interface import implementer
from twisted.conch.interfaces import IConchUser
from twisted.cred import portal, credentials
from twisted.conch.ssh.common import NS, getNS

# Python imports
import struct
import warnings
from base64 import b64encode

# Our imports
from textgame.Util import get_logger, Loggable
from textgame.User import SSHUser
from textgame.interfaces import IUsernameRequest

from textgame.World import World

logger = get_logger(__name__)

#: String representative of a guest user.
GUEST_USER = "__GUEST__"


class Disconnect(NamedTuple):
    """
    SSH disconnect messages.
    """
    from twisted.conch.ssh import transport as __transport
    HostNotAllowedToConnect = __transport.DISCONNECT_HOST_NOT_ALLOWED_TO_CONNECT
    AuthCancelledByUser = __transport.DISCONNECT_AUTH_CANCELLED_BY_USER
    NoMoreAuthMethodsAvailable = __transport.DISCONNECT_NO_MORE_AUTH_METHODS_AVAILABLE
    ConnectionLost = __transport.DISCONNECT_CONNECTION_LOST
    IllegalUserName = __transport.DISCONNECT_ILLEGAL_USER_NAME


class UserAuthMsg(NamedTuple):
    """
    SSH UserAuth message types.
    """
    from twisted.conch.ssh import userauth as __userauth
    Request = __userauth.MSG_USERAUTH_REQUEST
    Failure = __userauth.MSG_USERAUTH_FAILURE
    Success = __userauth.MSG_USERAUTH_SUCCESS
    Banner = __userauth.MSG_USERAUTH_BANNER
    InfoResponse = __userauth.MSG_USERAUTH_INFO_RESPONSE
    InfoRequest = __userauth.MSG_USERAUTH_INFO_REQUEST


@implementer(IUsernameRequest)
class UsernameRequest(object):
    """
    Represents a request to create an account, using a specific username.

    :param username: The username which is desired.
    """
    def __init__(self, username):
        self.username = username


class UsernameRequestData(NamedTuple):
    """
    Class representing data used for creating an account.

    Accompanies a :class:`UsernameRequest`.
    """

    #: Specifies whether this is a guest login.
    is_guest: bool

    #: If specified, a new character with this name should be created.
    #: If this is a guest login, this will be the name of the temporary guest character that should be created.
    new_character: Optional[str] = None

    #: If specified, this password should be used to create the new user.
    new_password: Optional[str] = None

    #: Public keys to save for this new user account, or None.
    public_keys: Sequence[str] = None


@implementer(portal.IRealm)
class SSHRealm:
    """
    This simple realm generates User instances.

    This is basically a factory for SSHUser instances. After SSH authentication
    has succeeded, the SSHRealm is provided with the username of the account that
    just logged in, and uses it to create and return an appropriate User instance.
    """

    def __init__(self, world):
        self.world: World = world

    def doesAvatarExist(self, avatarId):
        """
        Returns whether this avatar ID exists in the Realm.
        """
        # Query the database as to whether the username exists.
        return self.world.db.username_exists(avatarId)

    def requestAvatar(self, avatarId, mind: UsernameRequestData, *interfaces):
        """
        Requests that this Realm shall provide an "avatarAspect" which implements
        one of some list of interfaces. What this means for us is that we will
        create and return an SSHUser instance (which implements IConchUser).

        By the time this method is called, the user is already authenticated. This means that if the user does not
        exist, then the user must be created.

        :param avatarId: This is the username which we are getting an instance for. The avatar is what we are creating,
            and is the business logic object for a specific user (in this case an SSHUser instance).
        :param mind: An object that implements a client-side interface for this Realm.
            This is an object provided by our UserAuthService. We use this to provide more information about the
            user request.
        :param interfaces: list of interfaces that the mind is compatible with. In our
            case this is only ever going to be IConchUser, so we don't really care.
        :return: Should return a Deferred returning a tuple of (interface, avatarAspect, logout); actually returns the
            tuple directly.
        """
        if IConchUser in interfaces:
            # Return a tuple of (interface, avatarAspect, logout).
            # interface: one of the interfaces passed in.
            # avatarAspect: an instance of a class that implements that interface.
            # logout: a callable which will "detach the mind from the avatar". Spooky.
            if not self.world.db.username_exists(avatarId):
                self.world.db.create_user(avatarId, mind.new_password, mind.public_keys or [])

            if not mind.is_guest and mind.new_character is not None:
                self.world.db.create_character(avatarId, mind.new_character)

            avatar = SSHUser(self.world, avatarId)

            logout = avatar.on_logout if hasattr(avatar, "on_logout") and callable(avatar.on_logout) else lambda: None

            # TODO: Deferred?
            return interfaces[0], avatar, logout
        else:
            logger.error("SSHRealm: No supported interfaces")
            raise NotImplementedError("No supported interfaces found.")


class DebugSSHService(SSHService):
    """
    This replacement for the Conch SSHService simply logs
    a debug message for every packet received, with no
    changes in functionality. Used to debug subclasses of
    the Conch SSHService.
    """
    def packetReceived(self, messageNum, packet):
        logger.trace(f"{self.name}: packet {messageNum} ({self.protocolMessages[messageNum]}): {packet!r}")
        SSHService.packetReceived(self, messageNum, packet)


class UserAuthState(object):
    def __init__(self, auth, username, service):
        self.auth = auth
        self.pubkeys = []
        self.username = username
        self.desired_service = service

        # Work out whether this user is known
        self.user_is_known = self.auth.portal.realm.doesAvatarExist(username)

        # Stores keyboard-interactive state machine
        self._interactive = None

    def is_invalid(self, username, service_name):
        """
        Returns True if the supplied username and service name
        don't match stored values, which means this state is invalid.
        """
        return not all((username == self.username, service_name == self.desired_service))

    def add_key(self, blob):
        self.pubkeys.append(blob)

    def begin_interactive(self):
        self.auth.response_packet_count = 0
        self._interactive = KeyboardInteractiveStateMachine(self.auth, self.username, self.user_is_known)
    
    def continue_interactive(self, responses=None):
        self._interactive(responses or [])


class UserAuthService(SSHService, Loggable):
    """
    The UserAuthService replaces the standard SSH authentication service. This service customises the login experience
    in the following ways:

    - Unknown usernames are not rejected, instead, the keyboard-interactive method is used to offer the user a
      chance to register an account.
    - Unknown users who offered an SSH pubkey during authentication will be asked if they wish to use that key
      to authenticate in future.
    - Known users will be authenticated via pubkey, password, or keyboard-interactive.
    - Known users will be asked which character they want to play.
    
    Additionally:
    - On the internet, bots constantly attempt to brute-force SSH server passwords. This service includes code to
      detect and disconnect such bots.
    """
    #: Set the logger for this Loggable subclass.
    logger = logger

    #: Name of this SSH service.
    name = "ssh-userauth"
    #: List of the authentications we support.
    supportedAuthentications = ["publickey", "keyboard-interactive"]

    #: The protocol messages we support.
    protocolMessages = SSHUserAuthServer.protocolMessages

    #: List of blacklisted usernames.
    bad_usernames = (
        "root", "admin", "administrator",
        "MikroTik", "ubnt", "oracle",
        "support", "web", "tech",
        "user", "pi"
    )

    def _format_log(self, msg):
        """
        Get an appropriate log message (overrides Loggable formatter).
        """
        user = "" if self.state is None else f"{self.state.username}@"
        return f"[{user}{self.ip}:{self.port}] {msg}"

    def __init__(self):
        super().__init__()
        # Begin with no state, and we can't get the portal yet.
        #: Object storing state for this auth flow.
        self.state: Optional[UserAuthState] = None
        #: The portal for our login.
        self.portal: Optional[portal.Portal] = None

        # Keep track of a few values so that we can combat bots.
        #: Tracks the total number of state changes so far.
        self.state_changes = 0
        #: Tracks the total number of request packets so far.
        self.request_packet_count = 0
        #: Tracks the total number of response packets so far.
        self.response_packet_count = 0

        #: Used for when a user logs in with their character name in the username.
        self.character = None

        #: Stores the remote IP address.
        self.ip = "0.0.0.0"
        #: Stores the remote port.
        self.port = 0

    def serviceStarted(self):
        """
        Called when the service is started. This service starts automatically
        as soon as a user connects, in order to authenticate the user.
        """
        self.state = None
        # Store the portal for convenience. We use the portal for authentication.
        self.portal = self.transport.factory.portal

        self.ip = self.transport.transport.getPeer().host
        self.port = self.transport.transport.getPeer().port

        # Set this initially
        self.transport.logoutFunction = lambda: None

        # Set the avatar to None. We can use this to check if auth has succeeded.
        # If the avatar is still None, then auth did not succeed.
        self.transport.avatar = None

        # Send login banner.
        self.send_banner(self.transport.factory.bannerText)

    def serviceStopped(self):
        self.log_debug("Auth service stopping")

    # noinspection PyPep8Naming
    def ssh_USERAUTH_REQUEST(self, packet):
        """
        This method is called when a packet is received.
        The client has requested authentication.  Payload:
            string user
            string next service
            string method
            [authentication specific data]
        """
        self.request_packet_count += 1
        user, nextService, method, rest = getNS(packet, 3)
        user = user.decode('utf-8')
        method = method.decode('ascii')

        # First, check if the username is allowed.
        if user.lower() in self.bad_usernames:
            self.log_info(f"Disconnecting user: blacklisted username {user}")
            self.transport.sendDisconnect(
                Disconnect.IllegalUserName,
                f"Blacklisted username\n"
                f"Your username ({user}) is commonly used by spambots, and cannot be used here.\n"
                f"Please reconnect using a different, more unique username.")
            # self.transport.factory.banHost(self.ip)
            return

        # Next, check if there's a character name in the username.
        if ':' in user:
            user, self.character = user.split(':', 1)

        first = False
        if self.state is None or self.state.is_invalid(user, nextService):
            # If username or desired service has changed during auth,
            # the RFC says we must discard all state.
            self.state = UserAuthState(self, user, nextService)
            # We do keep track of how many state changes there have been.
            # This is used to thwart bots.
            self.state_changes += 1
            self.first_contact()
            first = True
        self.log_debug(f"Auth request for service {nextService.decode('ascii')}, method {method}.")
        if self.state_changes > 3 or self.request_packet_count > 20:
            self.log_info("Disconnecting user: too many attempts")
            self.disconnect_host_not_allowed("You are doing that too much!")

        if first and self.state.user_is_known:
            self.supportedAuthentications.append("password")

        if method == "none":
            # We want to push the user through keyboard-interactive.
            # This lets the client know what methods we do support.
            return self.send_authFail()

        if self.state.user_is_known:
            # Username is known to us! Do normal login.
            return self.handle_known_user(method, rest)

        else:
            # This user is not known to us.
            return self.handle_new_user(method, rest)

    def handle_new_user(self, method, rest):
        """
        Handles incoming auth from a new, unknown username.
        """
        if method == "publickey":
            # Store their pubkeys so they can use one to register with us.
            self.log_debug("Pubkey attempt")
            self.store_pubkey(rest)
        elif method == "keyboard-interactive":
            self.log_debug("Interactive attempt")
            # Start up the keyboard-interactive state machine.
            # This will take care of asking questions.
            self.state.begin_interactive()
        elif method == "password":
            # We told this client we don't support passwords
            # but they are ignoring us. Probably a bot.
            self.log_info("Disconnecting user: illegal password attempt")
            self.disconnect_host_not_allowed("This auth method is not allowed")
            self.transport.factory.ban_host(self.ip)
        else:
            # No idea what this is, but we don't support it.
            self.log_debug("Unknown {0} attempt".format(method))
            self.send_authFail()

    def handle_known_user(self, method, rest):
        if method == "publickey":
            # TODO: #7: Do public key auth for the user.
            #       Currently just fails this auth method.
            algo, blob, rest = getNS(rest[1:], 2)
            self.log_trace(self.key2str(algo, blob))
            self.send_authFail()

        elif method == "keyboard-interactive":
            self.log_debug("Interactive attempt")
            # Start up the keyboard-interactive state machine.
            # This will take care of asking questions.
            self.state.begin_interactive()

        elif method == "password":
            # TODO: #8: Do password auth for a known user.
            #       This will be a fast way to login if the character name is included in the username.
            self.send_authFail()

        else:
            # No idea what this is, but we don't support it.
            self.log_debug("Unknown {0} attempt".format(method))
            self.send_authFail()
    
    def first_contact(self):
        """
        Called the first time a user sends us a userauth request in this auth session.

        We currently only use this to log the user connection.
        """
        known_text = "Known" if self.state.user_is_known else "Unknown"
        self.log_info("{0} user {1} is authenticating".format(known_text, self.state.username))

    def store_pubkey(self, pubkey):
        """
        Temporarily store a publickey in the auth session state.

        These can later be retrieved and stored permanently if an account is created.
        """
        algo, blob, rest = getNS(pubkey[1:], 2)
        self.state.add_key(blob)
        self.log_debug(self.key2str(algo, blob))
        # Tell client that this key didn't auth them
        self.send_authFail()

    @staticmethod
    def key2str(algo, blob):
        return "{0} {1}".format(algo, b64encode(blob))

    def ssh_USERAUTH_INFO_RESPONSE(self, packet):
        self.response_packet_count += 1
        if self.response_packet_count > 20:
            self.log_info("Disconnecting user: too many attempts")
            self.disconnect_host_not_allowed("You are doing that too much!")

        resp = []
        try:
            num_resps = struct.unpack('>L', packet[:4])[0]
            packet = packet[4:]
            while len(resp) < num_resps:
                response, packet = getNS(packet)
                resp.append(response)
            if packet:
                # raise error.ConchError("%i bytes of extra data" % len(packet))
                self.log_warn("%i bytes of extra data" % len(packet))
                # Ignore extra data
        except Exception:
            # TODO: What kind of exceptions do we expect here?
            pass
        self.log_trace("Answers:"+', '.join(repr(r) for r in resp))
        self.state.continue_interactive([r.decode('utf-8') for r in resp])
    
    def ask_questions(self, questions):
        questions = list(questions)
        resp = []
        for message, isPassword in questions:
            resp.append((message, b'\0' if isPassword else b'\x01'))
        # TODO: document why we start with these
        packet = NS('') + NS('') + NS('')
        packet += struct.pack('>L', len(resp))
        for prompt, echo in resp:
            packet += NS(prompt) + echo
        self.transport.sendPacket(UserAuthMsg.InfoRequest, packet)
        self.log_debug("Asked the user a question")
        self.log_trace("Asked:\n"+'\n'.join(repr(q) for q in questions))

    def do_guest_login(self, character):
        """
        Log the user in to a guest character.
        """
        # TODO: #4: This currently logs in to the "Guest" character (hardcoded). This needs to be done better.
        # Consider requesting an avatar with IConchGuestUser or similar.

        # Obtain and store the avatar and logout function
        login_data = UsernameRequestData(True, character)
        (_, self.transport.avatar, self.transport.logoutFunction) = \
            self.portal.realm.requestAvatar(GUEST_USER, login_data, IConchUser)

        # Select the appropriate character on the avatar.
        if not self.transport.avatar.select_character("Guest"):
            self.transport.sendDisconnect(Disconnect.ConnectionLost, "Error: Guest character not found")

        # Finish authentication successfully
        self.succeed_auth()

    async def check_password(self, password):
        """
        Given a password, checks it.

        This invokes the credentials checker that's registered for this instance.
        """
        # Create a username/password pair and try to log in with it
        self.log_debug(f"Checking username/password pair {self.state.username}, {password}")
        creds = credentials.UsernamePassword(self.state.username, password)

        # Await the login function
        result = await self.portal.login(creds, UsernameRequestData(False), IConchUser)

        if result:
            # Auth succeeded
            _, self.transport.avatar, self.transport.logoutFunction = result
            self.log_debug(f"Auth callback: success")
            if self.character:
                if not self.transport.avatar.select_character(self.character):
                    # Requested character doesn't exist
                    self.log_info(f"User {self.state.username} requested missing character {self.character}")
                    self.character = None
            return True
        else:
            self.log_debug(f"Auth callback: failed")
            return False

    async def create_account(self, password, character_name):
        """
        Creates an account for the user who is currently trying to log in. Uses the SSHJ username.

        :param password: The password that the user has selected.
        :param character_name: The character name that the user has selected.
        :return: True if ...?
        """
        # Create a username/password pair
        creds = UsernameRequest(self.state.username)

        # Construct appropriate login data
        login_data = UsernameRequestData(False, character_name, password, self.state.pubkeys)

        # Await the login function
        # This is leveraging the Twisted system, the UsernameRequest should be handled and
        # understood as a request to create a new account.
        try:
            result = await self.portal.login(creds, login_data, IConchUser)
        except (twisted.cred.error.LoginFailed, NotImplementedError) as e:
            self.log_error(f"Account creation failed: {e!s}")
            return False

        if result:
            self.log_info("Account creation complete.")
        else:
            self.log_info("Account creation failed, username is taken.")
        return result

    def send_banner(self, banner):
        """
        Sends a Userauth Banner packet, causing the specified banner text to be
        displayed by the client.
        """
        self.transport.sendPacket(UserAuthMsg.Banner, NS(banner+'\n') + NS("en-US"))

    def send_authFail(self, partial=False):
        """
        Send a Userauth Failure packet containing the list of authentication methods
        which are still permitted.

        The "partial" parameter specifies whether the packet should indicate partial
        success, which tells the client that it gave correct credentials, however
        further credentials (such as a second factor) are still required to complete
        authentication. If omitted, this parameter defaults to False.
        """
        self.transport.sendPacket(
            UserAuthMsg.Failure,
            NS(','.join(self.supportedAuthentications)) + (b'\xff' if partial else b'\0')
        )

    def disconnect_no_auth_left(self, msg):
        """
        Sends a "No More Auth Methods Available" disconnect packet to the client.

        The parameter is a string to send as the disconnection message.
        """
        self.log_info("Disconnecting {0}: No more authentication methods left".format(self.ip))
        self.transport.sendDisconnect(Disconnect.NoMoreAuthMethodsAvailable, msg)

    def disconnect_host_not_allowed(self, msg):
        """
        Sends a "Host Not Allowed To Connect" disconnect packet to the client.

        The parameter is a string to send as the disconnection message.
        """
        self.log_info("Disconnecting {0}: Host Not Allowed".format(self.ip))
        self.transport.sendDisconnect(Disconnect.HostNotAllowedToConnect, msg)

    def disconnect_auth_cancelled(self, msg):
        """
        Sends a "Disconnect by application" disconnect packet to the client.

        :param msg: A string to send as the disconnection message.
        """
        self.transport.sendDisconnect(Disconnect.AuthCancelledByUser, msg)

    def succeed_auth(self):
        """
        Sends a Userauth Success packet to the client, then switches the transport
        to the client's desired service.
        """
        # Authentication has succeeded fully.
        # Obtain the service desired by the end user
        service = self.transport.factory.getService(self.transport, self.state.desired_service)
        self.transport.sendPacket(UserAuthMsg.Success, b'')
        self.transport.setService(service())

    # noinspection PyPep8Naming
    def _cbFinishedAuth(self, result):
        """
        The callback when user has successfully been authenticated.  For a
        description of the arguments, see L{twisted.cred.portal.Portal.login}.
        We start the service requested by the user.

        NOTE: I don't think this is used at all in our current flow. It can probably be removed.
        """
        (interface, avatar, logout) = result
        self.transport.avatar = avatar
        self.transport.logoutFunction = logout
        next_service = self.transport.factory.getService(self.transport, self.state.desired_service)
        if not next_service:
            raise error.ConchError(f'could not get next service: {self.nextService}')
        self.log_debug(f'{self.state.username} authenticated for {next_service!r}')
        self.succeed_auth()


class KeyboardInteractiveStateMachine(object):
    def __init__(self, auth: UserAuthService, username, is_known):
        """
        Constructor. Pass in a method that this state machine can use to ask the user questions.
        """
        self.auth = auth

        # Get the appropriate coroutine.
        # There's one for existing users and one for new users.
        self._state = self._existing(username) if is_known else self._new_user(username)

        # Invoke its first run
        self._state.send(None)

    class Response(Awaitable):
        def __await__(self):
            return (yield self)

    def __call__(self, responses=None):
        if responses is None:
            responses = []
        try:
            # Provide the generator with the responses we got.
            # In exchange, get back the next question to be asked.
            self._state.send(responses)
            # logger.debug(repr(awaitable))

        except StopIteration:
            return False
        return True

    def ask(self, *questions):
        self.auth.ask_questions((q, False) for q in questions)
        return self.Response()

    def ask_pass(self, *questions):
        self.auth.ask_questions((q, True) for q in questions)
        return self.Response()

    async def _new_user(self, username):
        """
        This method asks authentication questions to a user whose username is not known.
        """
        # ("\033[1mWelcome, \033[36m{0}\033[39m!\033[0m I don't recognise your username.\n"
        # "Would you like to \033[4mr\033[0megister, proceed as a \033[4mg\033[0muest, or "
        # "\033[4mq\033[0muit?\n(r/g/q): ".format(self.state.username), False)
        choice, = await self.ask(
            f"Welcome, {username}! I don't recognise your username.\n"
            "Would you like to [r]egister, proceed as a [g]uest, or [q]uit?\n(r/g/q): "
        )

        while len(choice) != 1 and choice.lower() not in "rgq":
            # self.auth.doGuestLogin(username)
            # return
            choice, = await self.ask(
                "Sorry, I don't understand your input.\nRegister, visit as a guest, or quit? (r/g/q): ")

        if choice == "q":
            self.auth.send_banner("Goodbye!")
            self.auth.disconnect_auth_cancelled("Please come again soon!")
            return
        elif choice == "g":
            character_name, = await self.ask("Please choose a name for your temporary character: ")
            self.auth.do_guest_login(character_name)
            return

        elif choice == "r":
            password, confirm = await self.ask_pass(
                # ("You are registering with the username \033[1;36m{0}\033[0m.\n"
                # "Please choose a password: ".format(self.state.username), True),
                f"You are registering with the username: {username}\nPlease choose a password: ",
                "Please re-type the password: "
            )
            while password != confirm:
                password, confirm = await self.ask_pass(
                    "Those passwords didn't match!\nPlease choose a password: ",
                    "Please re-type the password: "
                )
            character_name, = await self.ask("Choose a name for your first character: ")

            # TODO: #3: Does this return a value?
            success = await self.auth.create_account(password, character_name)
            if not success:
                self.auth.send_banner("Sadly, character creation failed due to an error.\n"
                                      f"Character {character_name} was not created.")
                self.auth.disconnect_auth_cancelled("Please visit again soon!")
            else:
                # TODO: #3: Log the user in to their new account.
                self.auth.disconnect_auth_cancelled("TODO: log back in to access your new account.")

    async def _existing(self, username):
        """
        This method asks questions to a user who is known.
        """
        welcome_back = f"Welcome back, {username}!"
        if self.auth.character is not None:
            welcome_back += f" You will connect as your character {self.auth.character}."

        password, = await self.ask_pass(
            f"{welcome_back}\nIf you are not {username}, please connect again using a different username.\n"
            f"Enter the password for {username}: "
        )

        # Check whether the password is valid
        attempts_remaining = 3

        # Await the Twisted deferred
        authenticated = await self.auth.check_password(password)

        # while self.auth.transport.avatar is None:
        while not authenticated:
            attempts_remaining -= 1
            if attempts_remaining <= 0:
                self.auth.disconnect_no_auth_left("Too many incorrect passwords.")
                return
            password, = await self.ask_pass("Incorrect password, try again: ")
            authenticated = await self.auth.check_password(password)

        if self.auth.character is None:
            characters = self.auth.transport.avatar.character_names
            if not characters:  # user has no characters for some reason
                character_name, = await self.ask(
                    "You have no characters.\nPlease choose a name for your first character: "
                )
                self.auth.transport.avatar.create_character(character_name)

            character_name, = await self.ask(
                f"Your characters: {','.join(characters)}\nWhat character do you want to use? "
            )
            while not self.auth.transport.avatar.select_character(character_name):
                character_name, = await self.ask("Character not found, try again: ")

        self.auth.succeed_auth()

