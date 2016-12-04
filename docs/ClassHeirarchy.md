## Definitions

Because I've confused myself over this enough already, I will define the following terminology before proceeding:

* **database**: The storage backend that contains the data used by this software.
* **world-object**: The abstract "thing" whose properties are described by a row in the `objects` table of the database. Not to be confused with **object**, which is an instance of a Python class.
* **DBid**: An integer number that uniquely identifies a particular world-object within the database; the primary-key of a row in the `objects` table.
* **Thing**: An instance of the `Thing` class or subclass, said instances each representing and providing access to the properties of a particular world-object.
* **world**: The virtual environment (consisting of linked rooms and their contents) that is collectively formed by all world-objects, represented by an instance of the `World` class. This instance provides access to `Thing` instances that represent world-objects within that world.
* **`Foo` class**: The `Foo` class itself (i.e. an instance of a metaclass such as the builtin `type`).
* **`Foo` instance**, or **a `Foo`**: An instance of the class `Foo`.

If you see an ambiguous reference to a class name and can't tell if it means an instance or the class, please let me know.

----

## Database.py

### `Database`

The `Database` class has the following responsibilities:

* Hash passwords ready for storage in the database
* Verify provided passwords against stored hashes
* Allow retrieval of a requested world-object from the database, returning it as a `Thing` instance
* Allow creation of new `Thing` instances for world-objects that did not previously exist in the database
* Allow retrieval and storage of any other data kept in the database, such as world-object properties.

The `Database` class is not specific to any particular database engine. It is an Abstract Base Class, which cannot be instantiated.
Instead, it is intended to be subclassed, which each subclass providing an implementation which is specific to a particular database engine.


### `DatabaseNotConnected`

An exception that is thrown when the database is not open/connected and an operation is requested that requires database access.

### `CredentialsChecker`

Implements the `twisted.cred.checkers.ICredentialsChecker` interface.

Responsibilities:

* Provide a Twisted-compatible interface that allows provided credentials to be verified against credentials stored in a `Database`.

### `AuthorizedKeystore`

Implements the `twisted.conch.checkers.IAuthorizedKeysDB` interface.

Responsibilities:

* Provide a Twisted-compatible interface that allows retrieval of a list of SSH authorized keys stored in a `Database`, given a username.



## SqliteDB.py

### `SqliteDatabase (Database)`

Inherits from `Database` (from Database.py).

Implements the `Database` class, backed by an Sqlite database.

### `Cursor`

A context manager that allows obtaining a cursor using a "with" statement. This ensures that if the context of the "with" block is exited for any reason
(such as an exception being raised), the cursor is correctly closed.



## Things.py

### `NotLoaded`

This class is never instantiated, but is used only as a unique placeholder value to represent a reference to a thing that is not loaded.
I don't think this class is ever used anywhere either. It can probably be deleted.

### `Thing`

This class represents a world-object in the database. It holds the properties of that world-object. Some of these properties will be references to other `Thing`s.

For example, given a `Thing` instance called `mything`, you could obtain the parent of the represented world-object (i.e. the world-object that contains this one) by using `mything.parent`.
In practice this won't return the actual `Thing` representing the parent, instead it will return a `ThingProxy` that will transparently load the real `Thing` only when an attempt is made to access
that `Thing`'s properties. To understand why this is the case, see `ThingProxy` below.

This class is a base class, but is not currently an Abstract Base Class. It probably should be.

### `Player (Thing)`

This `Thing` subclass represents a Player-type world-object. These types of objects are actors, they are a player's character in the world. This class provides additional methods to
let the world-object move around the world, locate nearby things, and observe its surroundings.

### `Room (Thing)`

This `Thing` subclass represents a Room-type world-object. This type of world-object exists to provide a location for other world-objects to exist in. This class provides no extra methods.

### `Item (Thing)`

This `Thing` subclass represents an Item-type world-object. This is a miscellaneous world-object that players can interact with, but which does not otherwise contribute to the structure of the world.
This class provides methods allowing these world-objects to be interacted with.

### `Action (Thing)`

This `Thing` subclass represents an Action-type world-object. This can be thought of as a verb that can be attached to another object. Invoking this verb will typically transport a player
to a new location, but may also run a script or cause some other change. Actions are most commonly used to provide a means for travelling between rooms, functioning as a named "exit" from that room.

### `Script (Thing)`

This `Thing` subclass represents a Script-type world-object. This is a type of item that can contain executable code, which will be run when this Script is the target of an Action,
and the Action is invoked. Script should probably be a subclass of Item, since aside from their executable nature they should otherwise function as an Item. Scripts have a method that
will run the executable code contained within them. The language of this code is currently undefined, but it is expected that scripts will support the Lua language.



## World.py

### `ThingProxy`

A `ThingProxy` is a wrapper around an actual `Thing` instance that provides lazy-loading and cache management.
The lazy-loading mechanic is required in order to prevent a `Thing`, when loaded, from also loading every `Thing` that it references.
A `ThingProxy` also maintains a timestamp that is used by a `World`'s caching mechanisms.

A `World` instance will use the `ThingProxyFactory` function to generate its own version of the `ThingProxy` class that references that particular `World` instance.

The following full explanation is taken from the `ThingProxy`'s docstring.

> The `ThingProxy` is a bit of Python magic that allows us to have object-like references to
`Thing`s without actually loading them from the database until needed.
>
> Other `Thing`s may keep references to this proxy even when the `Thing` it wraps has been unloaded.
Attempts to access an unloaded `Thing`'s attributes will trigger it to be reloaded from the database.
>
> **The Problem:**
>
> We want to use referential attributes of a `Thing` as though they were themselves `Thing`s,
for example we could use `myitem.parent.desc` to get the description of the room an item is in,
or perhaps `myitem.owner.link.name` to find out what our item's owner's home is called.
>
> However we do not want to directly reference another `Thing`! If we tried to do so, we would have
to load that `Thing` when we load the `Thing` that refers to it, and that in turn would require us
to load more `Thing`s, until we had loaded the entire database into memory... This would be wasteful
of memory and would result in a long intital loading time.
>
> One option is to lazy-load our referential attributes, i.e. a `Thing` will store only the integer DBref
of the other `Thing`s it references, and only load (and store) the real `Thing` when we attempt
to read the attribute that returns it. We have solved our loading problem, but now we have an
unloading problem. Because of Python's garbage collection, a `Thing` will remain in memory until there are no references left to it.
With the above system, it is non-trivial to locate and remove all of the references to a `Thing` that may be scattered across multiple other `Thing`s.
Over time, we would once again end up with most of the database in memory.
>
> **The Solution:**
>
> A `ThingProxy` instance is a lightweight object. It stores only three values: a reference to a
`Thing` instance, the DBref of the world-object that it represents, and a time value used for cache management.
>
> The lowest-level way for higher-level instances to obtain a `Thing` by its DBref is to call `World.get_thing(dbref)`,
which will actually return a `ThingProxy` instance for that DBref without instantiating a `Thing` or loading the
world-object from the database (the instance reference will be `None`). A new `ThingProxy` instance is only
created if one does not already exist for the given DBref, so there should only ever be one `ThingProxy`
instance per DBref (and therefore one per loaded `Thing`).
>
> As a result, anywhere that a `Thing` instance would normally store a reference to another `Thing`, it instead stores a
reference to the matching `ThingProxy`. Externally, the `ThingProxy` behaves just like a `Thing`, because all attribute
access (apart from DBref) is passed through to the real `Thing` instance, if there is one. If there isn't, then it is loaded from the database,
the `ThingProxy` stores the reference to it, and the attribute access completes successfully. This means that the `ThingProxy` now holds the ONLY reference to
the `Thing` instance, because all other references to that `Thing` are actually pointing to the `ThingProxy` instead.
>
> This solves the unloading problem, since now the only reference to the heavyweight `Thing` is in a known
location - in its corresponding `ThingProxy`, which the `World` instance has easy access to via its cache. To unload
a `Thing` from memory, the `ThingProxy` simply has to clear its reference to the `Thing` and let garbage
collection take care of the rest. The `ThingProxy` itself may be referred to from dozens of places, but
since it is so lightweight, it doesn't matter as much if a large amount of them end up in memory.

### `World`

An instance of this class represents the world that is made up of various `Thing`s (`Room`s, `Item`s etc) that reference each other.

It provides methods to manage a world and its objects at a high level, such as retrieving a particular object, retrieving a list of the contents of an object,
fetching a list of online players, or forcing an immediate save of the world to disk.



##  Interscript.py

This file contains classes that process Interscript, a functional scripting language with lisp-like syntax. It is intended to easily allow dynamic values to be substituted into a string that
will be shown to the user. However, it will be capable of much more, allowing a limited set of actions to be taken when a string is evaluated, such as: storing and retrieving values as properties,
moving a world-object, or invoking a script.

### `ResolvableText`

Instances of this class represent a string which contains embedded code at known locations in the strong. By "resolving" the string, the code will be executed, and the result of execution will be
substituted into the string at the code's former location. This class is used by the `Parser` class.

### `Parser`

An instance of this class is attached to a `Player` and used to parse any Interscript strings that the player comes across. The instance-per-player design allows the parsing to be performed
in the context of that player.



## User.py

This file contains classes that provide an interface between the human users and the world.

### `commandHandler`

A decorator that marks a method as a handler for a user command.

### `commandHelpText`

A decorator that attaches help text to a command handler. This help text will then be presented to the user via the help system.

### `IUserProtocol (Interface)`

It is unclear what this interface defines, or what the original intent was. It does not seem to be required.

### `Prelogin`

A currently-unused class that was intended to manage user commands in the period after the user has connected but before they have authenticated.

### `User`

An instance of this class represents a user who is currently connected to the world.

This class performs tasks such as:

 * Parsing incoming text from the user
 * Command processing
 * Locating actions that the user can execute
 * Implementing built-in commands like `@quit`
 * Sending appropriate messages to the user when something happens in the world around them
 * Sending an initial message when the user connects to a character

### `SSHUser (ConchUser, User)`

This class inherits from both User and ConchUser, and implements ISession.

It is responsible for constructing and setting up the user interface (Protocol) that the user sees when they connect.



## Network.py

### `BareUserProtocol (twisted.internet.protocol.Protocol)`

Currently non-functional code that supports a user connecting over plain text. Needs to be rewritten from scratch.

### `BasicUserSession (twisted.internet.protocol.Protocol)`

An older, even more broken version of `BareUserProtocol`. This class will be completely removed when `BareUserProtocol` is rewritten.

### `SSHRealm`

Implements `twisted.cred.portal.IRealm`. This class is invoked once a user successfully authenticates with SSH, and is tasked with returning an SSHUser instance for that user.

### `def SSHFactoryFactory`

This is a factory function that produces factory classes that produce SSH services. Don't ask.

### `SSHFactory (twisted.conch.ssh.factory.SSHFactory)`

An instance of this class is responsible for producing an SSH service (in this case, an `SSHUserAuthServer`) whenever somebody connects with SSH.

It is also responsible for storing SSH host keys, and for holding a `Portal` that authenticates users to our `SSHRealm`.

### `SSHPlayerAuthenticator (twisted.conch.ssh.userauth.SSHUserAuthServer)`

This work-in-progress class will responsible for custom authentication of SSH users. It will replace the default `SSHUserAuthServer` as the service returned by our `SSHFactory`.

This custom authenticator will allow users who do not yet have an account, to create one.

### `SSHServerProtocol (twisted.conch.insults.insults.ServerProtocol)`

Despite the name, this is actually a terminal transport which provides support for our SSH terminal protocol. This should be renamed. Basically this is a transport which, in addition
to sending and receiving raw data, also provides a bunch of methods that interact with a TTY on the remote end to move the cursor around, set scroll regions, and other things that would
normally involve sending ANSI sequences directly.

### `SSHProtocol (twisted.conch.recvline.HistoricRecvLine)`

This terminal protocol provides the user interface that a user interacts with when they connect with SSH. This interface has a separate text-input area at the bottom of the screen, while
incoming lines of text are displayed in a scrolling output area above the fixed text-entry area. The interface stores scrollback, allowing the output area to be scrolled and also allowing
the screen to be correctly redrawn if the terminal is resized. It also provides line-editing features, and supports input history (up and down arrow keys can access previously-input text).



## tmain.py

This file contains a main function which sets up the Twisted Reactor to listen on ports 8888 (for plaintext) and 8822 (for SSH), providing the appropriate factories for each, then runs the reactor.
Upon reactor shutdown, it will shutdown the world and close the database.