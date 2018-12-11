# Roadmap

This is the roadmap for this project.

## Initial Status

Since this roadmap was written part way through development, I first want to assess the status of the project in terms of features, as of the time this roadmap was written.

### Database

There is a working SQLite database implementation, accessed via an abstraction layer which has the potential to allow additional database implementations (e.g. PostgreSQL). It may be subject to change in future. The intent is to handle database structure changes using schema versions.

### Network

SSH connections are working on port 8822. SSH login was previously working using normal SSH password auth, but this left no way for unknown users to connect. SSH auth is currently undergoing a rework that is intended to allow for:

  * Single accounts having multiple associated characters
  * New users can connect and register without auth
  * Users can use their SSH key for auth
  * New users can have their SSH pubkey captured and stored for auth if they want to use it

Plain text connection on port 8888 has an implementation that is currently not functional. This needs to be brought up to a functional level, ideally with optional SSL on port 8899, and potentially with STARTTLS support.

### Interface (SSH)

Users connecting with SSH are presented with a client interface. This is currently functional and does not require any further work unless additional features are desired.

### World

A basic and functional world implementation exists.

It has:

* Working database loading and saving
* Working Player objects and Rooms
* Basic Actions and Items
* Non-functional Scripts
* A few basic built in commands
* Action look-up functionality

It needs:

* A full set of built in commands
* Working actions (player can traverse rooms)
* Working actions on items

### Scripting

"Interscript" is a LISP-like language designed to be parsed in strings such as room and player descriptions, action messages, etc. It is suitable for basic to intermediate scripting, and for creating interactive or dynamic environments.

* There is a working Interscript parser.
* There are only a few Interscript functions defined, but the framework for these functions is in place.
* There is currently no way to actually run Interscript from within the world.

For advanced scripting, Script objects can exist in the world. These are intended to hold and execute scripts written in more advanced scripting languages:

* Lua will be supported.
* Python may be supported, depending on ability to perform sandboxing.

There is currently no implementation for this type of scripting.

## Version 0.1

With the starting status laid out, here is what I want to see implemented in a 0.1 milestone:

### Database

Some changes will be needed here to support other changes. In particular, schema changes to allow multiple characters per account, and to allow for the storing of account preferences and SSH public keys.

### Network

First, I want to get the authentication rework functional. I want to be able to successfully connect with a new username, set a password, create a character, disconnect, then log back in with my password and use that character.

SSH keys will not be supported at this stage.

Second, I want non-SSH connection to work (for now, plaintext only). This will require a different auth flow.

### Interface (SSH)

No changes.

### World

Commands to create rooms and actions, and to set descriptions. Ability to link actions to rooms, such that rooms can be traversed via the actions.

### Scripting

Support Interscript in object descriptions.

## Version 0.2

*(To Be Completed)*
