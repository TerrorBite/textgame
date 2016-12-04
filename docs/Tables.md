# Table Schema

## `meta` table

This table holds key-value pairs that store metadata about the database.

Currently the only known key is `schema_version` which has a default value of `0`.

## `users` table

This table stores information about user accounts.

This is basically just a username and password pair that then links to the id of the player's object.

### Columns

- `id`: ID number for this account (unique, non-null unsigned integer). Currently unused, but will be foreign key for future character-account mapping table. (sqlite: alias to rowid)
- `username`: Username of this account.
- `password`: Password hash, stored in hexadecimal.
- `salt`: Salt used in password hash, stored in hexadecimal.
- `email`: Email address, used for account verification and password recovery.
- `obj`: Reference to the account's `Player`-type database object. In future this will be removed, and a new table will be added that maps characters to accounts, which will allow accounts to have multiple characters.

## `objects` table
Stores basic data about an object. This is the most important table in the database.

Any additional data is generally stored as properties on the object. Properties are stored in a separate table.

### Columns

- `id`: The database ID of the object. This is a unique, non-null unsigned integer. In sqlite, this is an alias to the built-in rowid.
- `name`: A name for this object (String).
    - Names do not need to be unique, with one exception: no object may be given the same name as an existing Player object, to prevent impersonation.
- `type`: A type value (Player, Room, Action, Item, Script). This is set at creation and cannot be modified.
- `flags`: A set of boolean flags that modify the object (long integer).
    - Flags have varying meaning depending on object type. Flags are listed elsewhere.
- `link`: The ID of an object that this object links to. May be null.
    - Setting the link of a Player, Item or Script to a valid container sets the object's home. These cannot be unlinked.
    - Setting the link of an Action determines either a script to execute or a room to transport the player to.
    - Setting the link of a Room currently has no effect.
- `parent`: The ID of the object that contains this object, i.e. the location of the object. Cannot be null. *(See below)*
    - Cannot be explicitly set, but is set implicitly by moving the object.
- `owner`: An owner (ID), must be a Player's ID. Players always own themselves.
- `money`: The quantity of currency carried by this object.
	- This is stored as a basic value instead of a property for the simple reason that objects can generally modify their own properties, and having players edit how much money they were carrying would be undesirable.
- `created`: Time this object was created. Set at creation and cannot be modified.
- `modified`: Time this object was last modified, where modification is defined as any of the object's basic data being altered, or a property value being set on the object.
- `lastused`: Time this object was last used. Defintion of "used" is a bit hard to pin down, as it varies depending on the type of object:
	- Player: Time of last login or logout, whichever was most recent.
	- Action: Last time the action was used.
	- Script: Last time the script was executed.
	- Room: Last time the contents of the room were changed. (?)
	- Item: Last time the contents were changed, or last time it was moved. (??)

### Notes on parents
    
Every object must have a parent, and cannot have multiple parents, but can contain multiple child objects.
All objects must be able to trace their "ancestry" back to ID 0, forming a tree structure rooted at Room #0, whose "parent" is itself.
The ancestry constraint sensibly prevents an object from ever containing itself, its parent, or one of its ancestors.

Certain types of object are limited in what they can contain:
- `Rooms` may contain any type of object.
	- Rooms may only be contained by another Room.
    - A room's purpose is to contain other objects.
- `Players` can contain Items, Scripts, Actions and even other Players.
    - A player may contain another in order to allow a player to "ride" or "carry" another. A Player carried in this way will still see and interact with the world as though they were in the same room as the one carrying them.
    - *note: is this even a good idea?*
- `Items` may contain other Items, Scripts, and Actions. May not contain Rooms or Players.
- `Scripts` may contain other Scripts, Actions, and Items. *(why items?)*
	- A Script contained by another Script will appear as a submodule to its parent.
    - See SCRIPTS for explanation.
- `Actions` cannot contain anything.
    - Actions can be considered as verbs that describe what an object can do or what the exits from a room are. Verbs don't have contents.


## `deleted` table

Contains a list of IDs whose objects have been marked as deleted.
When a user requests deletion of an object, it is flagged as deleted, and its ID is added to this table. This gives users a chance to undo.

When a new object is created, the first ID in this table (if any) is removed and claimed as the ID of the new object.
The details of the deleted object with that ID are then overwritten with those of the new object, and the old object is lost forever.
This system allows IDs to be reused and doesn't leave "holes" in the database.

When an object is deleted, any objects contained inside the deleted object fall through into its parent. Any objects that link to the deleted object will have their links updated to the deleted object's parent.

If the deleted object is a player, then objects once owned by the player will become owned by #0: this value has the special meaning of "Unowned" and allows anyone to claim an object as theirs. (The @disown command can be used to change an object you use to unowned, and the @claim command can be used to claim such an object).

## `props` (properties) table

to be written

## Notes on message properties

- succ: A success message.
    - For Actions, a player will see this message when they successfully invoke the Action.
    - For Items, a player will see this message when they pick up the item.
- fail: A failure message.
    - For Actions, a player will see this message when they fail the Action's lock, or the script invoked by the Action returns failure.
    - For Items, a player will see this message when they fail to pick up an item.
- osucc: An external success message, which others nearby will see.
    - The message will be automatically prepended by the player's name.
    - For Actions, players in the same room will see this message when a player successfully uses the Action.
    - For Actions linked to a room (Exits), replaces the standard "X has left" message when a player uses the exit.
    - For Items, players in the same room will see this message when a player successfully picks up the item.
- ofail: An external failure message, which others nearby will see.
    - The message will be automatically prepended by the player's name.
    - For actions, this message is seen by others in the same room when a player fails the action's lock, or a linked script fails.
    - For Items, this message is seen seen by other players in the room when a player fails to pick up the item.
- drop: Similar to success value.
    - The message will be automatically prepended by the player's name.
    - For Exits, this message is broadcast to all players in the destination room, replacing the standard "X has arrived" message.
    - For Items, this message is seen by other players in the room where a player drops this item.
- There is no "drop fail" message.
    
## `locks` table

This is a many-to-many relationship table, holding the individual values from an object's basic lock list.

Basic locks are described [here](#). *(todo: write locks document)*

### Columns

Each row is a single entry in an object's locks list. An entry is comprised of:
- `obj`: The ID of the object whose lock list this item belongs in.
- `lock`: The ID of the object that can pass the lock.
    
## `acl` (access control list) table

This is a many-to-many relationship table, holding the individual values from an object's access control list.
Each entry has associated flags that specify what level of access that player has to this object.

Access lists are inherited from the parent, but note that only objects which have the ACL flag enabled will be affected.

Note that Access Control Lists are an advanced concept and are currently not required or used.

### Columns
- `obj`: ID of the object which this ACL entry applies to.
- `player`: ID of the player whose access to this object is being controlled. 
- `flags`: A bitfield of flags that describe what specific permissions the player has to access this object.

## `scripts` table

This standalone table holds the code of scripts. It exists as a separate table to save space (as few of a db's objects are likely to be scripts), and also to ensure the script engine doesn't have to deal with the way that properties work.