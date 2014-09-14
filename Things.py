from Util import log, LogLevel

class Thing(object):
    """Represents a database object."""

    # Basic properties

    def __init__(self, world,
            obj, parent, owner, name, dbtype, flags, link=None, desc=None):

        # Keep a reference to the world instance
        self._world = world

        # Validation checking
        """Returns a value indicating whether or not this Thing needs to be saved to the database.

        If this instance is "dirty", then it should be saved to the database by calling its save() method."""
        self.dirty = False

        """This value indicates whether or not this instance still contains valid data about a Thing.

        False indicates that this instance is out of date, and should be discarded in favor of requesting a new instance from the database."""
        self.valid = True

        # Set basic params
        self._obj, self._dbtype, self._owner_id, self._parent_id = (obj, dbtype, owner, parent)
        self._name, self._flags, self._desc, self._link_id = (name, flags, desc, link)

        # References to other objects stay as None until called upon
        self._parent, self._owner, self._link = (None, None, None)

        log(LogLevel.Trace, 'A new Thing was instantiated with (ID:{0}) (name:{1}) (parentID:{2})'.format(self._obj, self._name, self._parent_id))

    def save(self):
        "Forces an immediate save of this Thing to the database."
        assert self.valid, "Refusing to save an invalidated Thing to the database, as this Thing may be out of date."
        self._world.save_thing(self)

    def invalidate(self):
        self.valid = False

    def id(self):
        return self._obj

    def parent(self):
        if not self._parent or not self._parent.valid:
            self._parent = self._world.get_thing(self._parent_id)
        return self._parent

    def parent_id(self):
        return self._parent_id

    def owner(self):
        if not self._owner or not self._owner.valid:
            self._owner = self._world.get_thing(self._owner_id)
        return self._owner
    
    def owner_id(self):
        return self._owner_id

    def link(self):
        if not self._link or not self._link.valid:
            self._link = self._world.get_thing(self._link_id)
        return self._link

    def link_id(self):
        return self._link_id

    def dbtype(self):
        return self._dbtype

    def contents(self):
        """Retrieves a list of objects contained in this object."""
        return self._world.get_contents(self)

    def desc(self, looker):
        #in future put extra processing here
        return self._desc if self._desc else "This thing looks nondescript."
    
    def name(self):
        return self._name

    def get_flag(self, flag):
        return False # or True if that flag is set

class Player(Thing):
    """A Player is an object that represents an actual person - it is their avatar. Players can move around and talk and stuff."""

    def __init__(self, *params):
        Thing.__init__(self, *params)
        log(LogLevel.Debug, 'A new Player object was instantiated!')

    def look(self, exit=None):
        """Returns a text description of this player's surroundings,
        or of a particular exit if specified."""
        if exit is None: return "You see {0}.\r\n{1}".format(self.parent().name(),self.parent().desc(self))
        if exit.lower() is 'me': return "You see {0}.\r\n{1}".format(self.name(), self.desc(self))

        actions = filter(lambda x: isinstance(x, Action), self.parent().contents() + self.contents())
        if exit.startswith('#'):
            actions = filter(lambda x: exit[1:] == x.id(), actions)
        else:
            actions = filter(lambda x: x.name().lower().startswith(exit.lower()), actions)
        if not actions: return "You can't look that way."
        elif len(actions) > 1: return "I don't know which one you mean!"
        return actions[0].desc(self)

    def go(self, action):
        """Finds an action named action and executes it."""
        return "You can't go that way!"

class Room(Thing):
    """ herp derp """
    #def contents(self):
        #pass

class Item(Thing):
    """An item is an object that players can manipulate. Anything which isn't a Script, Player, Room or Action is an Item."""

    def pickup(self, getter):
        pass

    def drop(self, dropper):
        pass

class Action(Thing):
    """Aaaaaaaaaaaaaa"""

    def use(self, user):
        pass

class Script(Thing):

    def run(self, initiator):
        pass
