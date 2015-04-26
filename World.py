from Database import DBType
from SqliteDB import SqliteDatabase as Database
from Things import Thing
from Util import log, LogLevel
from twisted.internet import task
import time


class ThingProxy(object): 
    """
    Lightweight wrapper around a Thing object.
    Other Things may keep references to this proxy even when the Thing it wraps has been unloaded.
    Attempts to access an unloaded Thing's attributes will trigger it to be reloaded from the database.
    """

    def __init__(self, world, objid):
        object.__setattr__(self, '_thing', None)
        object.__setattr__(self, '_world', world)
        object.__setattr__(self, '_id', objid)
        object.__setattr__(self, 'cachetime', 0)
        
        # Cache ourself
        assert objid not in world.cache, "Cache overwrite detected!"
        world.cache[objid] = self
        
    def __repr__(self):
        return "<ThingProxy({0}#{1}) at 0x{2:08x}>".format(self._thing.type.__name__ if self._thing else 'Unknown', self._id, id(self))

    def __getattr__(self, name):
        #log(LogLevel.Trace, "Attempting access for (#{0}).{1}".format(self._id, name))
        thing = object.__getattribute__(self, '_thing')
        if not thing:
            thing = self._world.load_object(self._id)
            assert thing is not None, "The thing is None!"
            object.__setattr__(self, '_thing', thing)
            self._world.live_set.add(self)
        self.cachetime = int(time.time())
        return getattr(thing, name) 

    def __setattr__(self, name, value):
        if not hasattr(self, name):
            if not self._thing:
                object.__setattr__(self, '_thing', self._world.load_object(self._id))
                self._world.live_set.add(self)
            self.cachetime = int(time.time())
            return setattr(self._thing, name, value)
        return object.__setattr__(self, name, value)
    
    def __getitem__(self, key):
        return self.world.db.get_property(self._id, key)

    def __setitem__(self, key, value):
        self.world.db.set_property(self._id, key, value)

    # Do not trigger a reload solely to obtain the ID that we already know
    # Override underlying Thing's id property
    @property
    def id(self):
        "Gets the database ID for this Thing. Read-only."
        return self._id

    def unload(self):
        if self._thing:
            self._thing.save()
            self._thing = None
        self._world.live_set.discard(self)

class World(object):
    """The World class represents the game world. It manages the collection of objects that together comprise the world."""

    def __init__(self):
        self.db = Database()
        self.cache = {}
        self.live_set = set()
        self.cache_task = task.LoopingCall(self.purge_cache)
        self.cache_task.start(300)
        pass

    def close(self):
        self.db.close()
    
    def connect(self, username, password=None):
        """Connects a player to the world."""
        if password is not None:
            obj = self.db.player_login(username, password)
            if obj == -1: return None
        else:
            obj = self.db.get_player_id(username)
        return self.get_thing(obj) if obj else None

    def get_thing(self, obj):
        """
        Retrieves the Thing with the given database ID.

        Actually returns a ThingProxy that facilitates lazy-loading of Things and
        allows Things to be unloaded in the background to save memory, and transparently
        loaded again upon demand.
        """
        if not obj in self.cache:
            log(LogLevel.Trace, "Cache: MISS #{0}".format(obj))
            return ThingProxy(self, obj)
        else:
            log(LogLevel.Trace, "Cache: Hit #{0}".format(obj))
            return self.cache[obj]

    def load_object(self, obj):
        return self.db.load_object(self, obj)

    def purge_cache(self, expiry=3600):
        "Remove all cached objects older than the given time."
        threshold = int(time.time()) - expiry
        cachesize = len(self.cache)
        #self.cache = [x for x in self.cache if x[1] > threshold]
        objects = self.live_set.copy()
        for obj in objects:
            if obj.cachetime < threshold:
                obj.unload() # Save and unload the object
            elif obj.dirty:
                obj.force_save()
        log(LogLevel.Trace, "Cache: Purged {0} stale objects from memory".format(len(objects)-len(self.live_set)))

    def get_contents(self, thing):
        """Returns a tuple of Things that the given Thing contains."""
        try:
            # Get list of IDs
            items = self.db.get_contents(thing.id)
            # Get Things and return them
            return map(lambda x: self.get_thing(x), items)
        except AttributeError:
            raise TypeError("Expected a Thing as argument")

    def save_thing(self, thing):
        self.db.save_object(thing)

    def find_user(self, name):
        """
        Find a connected user by the given character name.
        """
        #TODO: Return user
        pass

    def list_players(self):
        """
        Return a list of all connected characters as Player objects.
        """
        pass

# Singleton instance reference
_world = None

# Singleton getter
def getWorld():
    global _world
    if not _world:
        # Instantiate singleton
        log(LogLevel.Debug, "Instantiating world singleton")
        _world = World()
    
    return _world

