from Util import log, LogLevel
import time

class NotLoaded:
    pass

class Thing(object):
    """Represents a database object."""

    # Editable database attributes
    dbattrs = ('name', 'flags', 'parent', 'owner', 'link', 'money')
    msgattrs = ('desc', 'succ', 'fail', 'osucc', 'ofail', 'drop')

    # Basic properties

    def __init__(self, world, obj,
            name, dbtype, flags,
            parent_id, owner_id, link_id, money,
            created, modified, lastused):

        # Keep a reference to the world instance
        self.world = world

        # Validation checking
        """Returns a value indicating whether or not this Thing needs to be saved to the database.

        If this instance is "dirty", then it should be saved to the database by calling its save() method."""
        self.dirty = False

        # Set basic params
        self._obj, self._dbtype = (obj, dbtype)
        self.name, self.flags, self.money = (name, flags, money)
        self._created, self._modified, self._lastused = (created, modified, lastused)

        self._desc = world.db.get_property(obj, '_/desc')

        self.owner = world.get_thing(owner_id)
        self.parent = world.get_thing(parent_id)
        self.link = world.get_thing(link_id) if link_id else None

        log(LogLevel.Trace, 'A new Thing was instantiated with (ID:{0}) (name:{1}) (parentID:{2})'.format(self._obj, self.name, self.parent.id))
        self.__setattr__ = self._setattr

    def __repr__(self):
        return "<{0}#{1} at 0x{2:08x}>".format(type(self).__name__, self._obj, id(self))

    #def __getattr__(self, name):
    #    if name in msgattrs:
    #        # DB load messages
    #    return object.__getattr__(self, name)

    def _setattr(self, name, value):
        if name in (type(self).dbattrs + type(self).msgattrs):
            self.modified = time.time()
            self.dirty = True
            log(LogLevel.Trace, "{0}#{1} marked dirty for writing {2}".format(self.name, self._obj, name))
        object.__setattr__(self, name, value)

    def force_save(self):
        "Forces an immediate save of this Thing to the database."
        self.world.save_thing(self)
        self.dirty = False

    def save(self):
        "Saves this object to the database, only if it has changed since it was loaded."
        if self.dirty:
            self.force_save()

    def __getitem__(self, key):
        return self.world.db.get_property(self._obj, key)

    def __setitem__(self, key, value):
        self.world.db.set_property(self._obj, key, value)

    @property
    def id(self):
        "Gets the database ID for this Thing. Read-only."
        return self._obj

    @property
    def dbtype(self):
        "Gets the database type of this Thing. Read-only."
        return self._dbtype

    @property
    def type(self):
        "Gets the Python type of this Thing (useful with a ThingProxy). Read-only."
        return type(self)

    @property
    def desc(self):
        "Gets the description of this Thing."
        return self._desc

    @desc.setter
    def desc(self, value):
        self.world.db.set_property(self._obj, '_/desc', value)
        self._desc = value

    @property
    def created(self):
        "Gets the time (seconds since Unix epoch) that this Thing was created."
        return self._created

    @property
    def modified(self):
        "Gets the time (seconds since Unix epoch) that this Thing was last modified."
        return self._modified

    @property
    def lastused(self):
        "Gets the time (seconds since Unix epoch) that this Thing was last used."
        return self._lastused

    @property
    def contents(self):
        """Retrieves a list of objects contained in this object."""
        items = self.world.get_contents(self)
        log(LogLevel.Trace, "Obtained contents for {0}: {1}".format(repr(self), repr(items)))
        return items

    def get_desc_for(self, looker):
        #in future put extra processing here
        return self.desc if self.desc else "You see nothing special."
    
    def hasflag(self, flag):
        return False # or True if that flag is set

class Player(Thing):
    """
    A Player is an object that represents an actual person - it is their avatar.
    Players can move around and interact with the game world.
    
    A Player's contents is their inventory - the items they are carrying. They can carry anything except Rooms.
    """

    def __init__(self, *params):
        Thing.__init__(self, *params)
        log(LogLevel.Debug, 'A new Player object was instantiated!')

    def look(self, exit=None):
        """Returns a text description of this player's surroundings,
        or of a particular exit if specified."""
        if exit is None: return "You see {0}.\r\n{1}\r\nExits: {2}".format(self.parent.name, self.parent.get_desc_for(self),
                ', '.join([x.name for x in self.parent.contents if x.type is Action]))
        if exit.lower() is 'me': return "You see {0}.\r\n{1}".format(self.name, self.get_desc_for(self))

        stuff = self.parent.contents + self.contents
        return "You can't see that clearly. (Not yet implemented)"


    def go(self, action):
        """Finds an action named action and executes it."""
        # TODO: Execute actions
        actions = filter(lambda x: x.type is Action, self.parent.contents + self.contents)
        log(LogLevel.Trace, "Found actions: {0}".format(repr(actions)))
        if exit.startswith('#'):
            actions = filter(lambda x: exit[1:] == x.id(), actions)
        else:
            actions = filter(lambda x: x.name.lower().startswith(exit.lower()), actions)
        if not actions: return "You can't go that way."
        elif len(actions) > 1: return "I don't know which one you mean!"


class Room(Thing):
    """
    A Room is an object whose primary purpose is to contain other objects.
    It """
    #def contents(self):
        #pass

class Item(Thing):
    """An item is a generic object that players can manipulate. Anything which isn't a Script, Player, Room or Action is an Item."""

    def pickup(self, getter):
        pass

    def drop(self, dropper):
        pass

class Action(Thing):
    """Aaaaaaaaaaaaaa"""
    # ^ I was either drunk or really tired when I wrote this code

    def use(self, user):
        log(LogLevel.Trace, "{0} used {1}".format(user, self))

class Script(Thing):

    def run(self, initiator):
        pass
