from Database import DBType
from SqliteDB import SqliteDatabase as Database
from Things import Thing
from Util import log, LogLevel
from twisted.internet import task
import time

def ThingProxyFactory(_world):
    class ThingProxy(object): 
        """
        Lightweight wrapper around a Thing object.

        The ThingProxy is a bit of Python magic that allows us to have object-like references to
        Things without actually loading them from the database until needed.

        Other Things may keep references to this proxy even when the Thing it wraps has been unloaded.
        Attempts to access an unloaded Thing's attributes will trigger it to be reloaded from the database.

        The Problem:

        We want to use referential attributes of a Thing as though they were themselves Things,
        for example we could use 'myitem.parent.desc' to get the description of the room an item is in,
        or perhaps 'myitem.owner.link.name' to find out what our item's owner's home is called.

        However we do not want to directly reference another Thing! If we tried to do so, we would have
        to load that Thing when we load the Thing that refers to it, and that in turn would require us
        to load more Things, until we had loaded the entire database into memory... This would be wasteful
        of memory and would result in a long intital loading time.

        One option is to lazy-load our referential attributes, i.e. to only load a Thing when we attempt
        to read the attribute that returns it. We have solved our loading problem, but now we have an
        unloading problem. We cannot unload a Thing from memory until there are no references left to it.
        Eventually we would once again end up with most of the database in memory.
        
        The Solution:

        The ThingProxy is a lightweight object. It stores only three values: a reference to a Thing, the database
        ID of the Thing that it references, and a time value used for cache management. It behaves just like a Thing,
        by passing all attribute access through to the real Thing, transparently loading the Thing if required.
        
        The canonical way to obtain a Thing is to call World.get_thing(id), which returns a ThingProxy for that id.
        A new ThingProxy is only created if one does not already exist for the given id, so there should only ever
        be one ThingProxy per Thing.

        As a result, anywhere that a Thing would normally store a reference to another Thing, it instead stores a
        reference to the Thing's ThingProxy. Upon first attribute access, the Thing is loaded from the database,
        and the ThingProxy stores the reference to it. Note that the ThingProxy now holds the ONLY reference to
        the Thing itself, as all other references are to the ThingProxy instead.

        This solves the unloading problem, since now the only reference to the heavyweight Thing is in a known
        location - in its corresponding ThingProxy, which the World has easy access to via its cache. To unload
        a Thing from memory, the ThingProxy simply has to clear its reference to the Thing and let garbage
        collection take care of the rest. The ThingProxy itself may be referred to from dozens of places, but
        since it is so lightweight, it doesn't matter as much if a large amount of them end up in memory.
        """

        # Store a class-wide reference to the World that created us
        world = _world

        def __init__(self, world, objid):

            # Our setattr is overridden, work around this.
            self.__dict__.update({
                '_thing': None,  # Reference to the underlying object
                '_id':    objid, # Database ID of the object
                'cachetime': 0,  # Used to calculate cache age
                '_dirty': False, # If the underlying instance is "dirty", then it should
                                 # be saved to the database by calling its save() method.
            })

            
            # If there is already a cache entry for this id, then this is a Bad Thing,
            # because that means two ThingProxies now exist for the same Thing.
            assert objid not in world.cache, "Cache overwrite detected!"

            # Cache ourself in the world
            world.cache[objid] = self
            
        def __repr__(self):
            return "<ThingProxy({0}#{1}) at 0x{2:08x}>".format(self._thing.type.__name__ if self._thing else 'Unknown', self._id, id(self))

        def __getattr__(self, name):
            """
            Called when attempting to access an attribute that does not exist.

            If this is the case, then we want to pass the access through to our underlying Thing.
            If the Thing is not loaded, then we will load it now.
            """
            # Note that __getattr__ is ONLY called for attributes that do not already exist
            #log(LogLevel.Trace, "Attempting access for (#{0}).{1}".format(self._id, name))

            # We use __getattribute__ here, just in case self._thing doesn't
            # exist for some reason (which would cause an infinite loop).
            thing = object.__getattribute__(self, '_thing')
            if not thing:
                # Thing isn't loaded. Load it
                thing = self._load_thing()
            # I don't know why the two lines below are there:
            #if name=='dirty':
            #    self.cachetime = int(time.time())
            return getattr(thing, name) 

        def _load_thing(self):
            """
            Called when the underlying Thing needs to be loaded.
            """
            thing = self.world.db.load_object(self.world, self._id)
            assert thing is not None, "The thing in {0} is None! This shouldn't happen".format(self)
            # Use object.__setattr__ to set self._thing because we overrode our own __setattr__
            object.__setattr__(self, '_thing', thing)
            # Add ourselves to the live set, this tells the World to consider us for unloading
            self.world.live_set.add(self)
            return thing

        def __setattr__(self, name, value):
            if name not in self.__dict__:
                if not self._thing:
                    self._load_thing()
                # Update cache time and mark dirty, since object was touched
                self.cachetime = int(time.time())
                self._dirty = True
                return setattr(self._thing, name, value)
            return object.__setattr__(self, name, value)
        
        # This is pretty much a direct copy/paste from Thing
        def __getitem__(self, key):
            """
            Thing property getter.
            """
            return self.world.db.get_property(self._id, key)

        # This is pretty much a direct copy/paste from Thing
        def __setitem__(self, key, value):
            """
            Thing property setter.
            """
            self.world.db.set_property(self._id, key, value)

        # Override underlying Thing's id property so that we don't trigger
        # a Thing reload just to obtain the ID that we already store
        @property
        def id(self):
            """
            Gets the database ID for this Thing. Read-only.
            """
            return self._id

        @property
        def dirty(self):
            """
            Gets whether this Thing needs to be saved. Read-only.
            """
            return self._dirty
        
        def save(self):
            """
            Saves this Thing to the database, only if it has been changed since it was last loaded.
            """
            if self._dirty:
                log(LogLevel.Trace, "ThingProxy#{0}: Saving dirty Thing".format(self._id))
                self._thing.force_save()
                self._dirty = False

        def unload(self):
            """
            Forces the Thing referred to by this ThingProxy to be unloaded.
            """
            if self._thing:
                self.save()
                self._thing = None
            # remove ourself from the live set
            self.world.live_set.discard(self)

        # End of ThingProxy class
    return ThingProxy
    # End of ThingProxyFactory

class World(object):
    """
    The World class represents the game world. It manages the collection of objects that together comprise the world.
    """

    def __init__(self):
        self.db = Database()
        self.cache = {}
        self.live_set = set() # The live set tracks ThingProxies that are keeping Things loaded
        self.cache_task = task.LoopingCall(self.purge_cache)
        self.cache_task.start(300)
        self.ThingProxy = ThingProxyFactory(self)

    def close(self):
        # Immediately purge (and save, if neccessary) all cached objects
        self.purge_cache(-1)
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
            return self.ThingProxy(self, obj)
        else:
            log(LogLevel.Trace, "Cache: Hit #{0}".format(obj))
            return self.cache[obj]

    def purge_cache(self, expiry=3600): #TODO: Rename this function?
        """
        Remove from the cache all cached objects older than the given time.
        
        Save any objects that have been modified since they were cached.
        """
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
        #TODO: Review this function vs. calling thing.force_save()
        # Save Thing basic info
        self.db.save_object(thing)
        # Save any modified properties of the Thing
        for prop in thing._propdirty:
            self.db.set_property(thing.id, prop, thing._propcache[prop])

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

