from Database import Database, DBType
from Things import Thing
from Util import log, LogLevel
from twisted.internet import task
import time

class World:
    """The World class represents the game world. It manages the collection of objects that together comprise the world."""

    def __init__(self):
        self.db = Database()
        self.cache = {}
        self.cache_task = task.LoopingCall(self.purge_cache)
        self.cache_task.start(300)
        pass

    def close(self):
        self.db.close()
    
    def connect(self, username, password):
        """Connects a player to the world."""
        obj = self.db.player_login(username, password)
        if obj == -1: return None
        return self.get_thing(obj)
        pass

    def get_thing(self, obj):
        if type(obj) is not int:
            raise TypeError("Expected an int as argument")
        if not obj in self.cache:
            log(LogLevel.Trace, "Cache: MISS #{0}".format(obj))
            self.cache[obj] = [self.db.load_object(self, obj), int(time.time())]
        else:
            log(LogLevel.Trace, "Cache: Hit #{0}".format(obj))
            self.cache[obj][1] = int(time.time())
        return self.cache[obj][0]

    def purge_cache(self, expiry=3600):
        "Remove all cached objects older than the given time."
        threshold = int(time.time()) - expiry
        cachesize = len(self.cache)
        #self.cache = [x for x in self.cache if x[1] > threshold]
        for obj in self.cache.keys():
            if self.cache[obj][1] < threshold:
                self.cache[obj][0].save() # Save to database so we don't lose data
                self.cache[obj][0].invalidate() # Invalidate existing references to this instance
                del self.cache[obj] # Finally, remove the cache entry
        log(LogLevel.Trace, "Cache: Purged {0} stale objects from cache".format(cachesize-len(self.cache)))


    def get_contents(self, thing):
        """Returns a tuple of Things that the given Thing contains."""
        try:
            items = self.db.get_contents(thing.id())
            return map(lambda x: self.get_thing(x), items)
        except AttributeError:
            raise TypeError("Expected a Thing as argument")

    def save_thing(self, thing):
        self.db.save_object(thing)


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

