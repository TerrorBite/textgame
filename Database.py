
import sqlite3, hashlib, struct, random

from Things import *
from Util import enum, log, LogLevel

DBType = enum('Room', 'Player', 'Item', 'Action', 'Script')

active = True

class DatabaseNotConnected(Exception):
    pass

class Database:

    def create_hash(self, password):
        """Create a password hash and matching salt for the first time."""
        salt = struct.pack('Q', random.getrandbits(64))
        pwhash = self.hash_pass(password, salt)
        return pwhash, salt.encode('hex_codec')

    def hash_pass(self, password, salt):
        """Compute a password hash given a plaintext password and a binary salt value."""
        return hashlib.sha1("{0}{1}".format(salt, hashlib.sha1(password).digest())).hexdigest()

    def player_login(self, username, password):
        """Logs in a player. Returns -1 if login failed, or a database ID if successful."""
        
        if not active: raise DatabaseNotConnected()

        log(LogLevel.Trace, "Verifying salted sha1 password hash for user {0}, password {1} (redacted)".format(username, '*'*len(password)))
        c = self.conn.cursor()
        c.execute("SELECT password, salt, obj FROM users WHERE username == ?", (username,))
        result = c.fetchone()
        if not result:
            log(LogLevel.Trace, "No matching records in database")
            return -1
        pwhash, salt, obj = result
        log(LogLevel.Trace, "Successfully retrieved hash={0}, salt={1}, obj={2} from database".format(pwhash, salt, obj))
        ret = obj if pwhash == self.hash_pass(password, salt.decode('hex_codec')) else -1
        if ret == -1: 
            log(LogLevel.Debug, "Password hash mismatch for user {0}".format(username))
        return ret

    def __init__(self):
        # Sanity check sqlite version
        v = sqlite3.sqlite_version_info
        if(v[0] < 3 or (v[0] == 3 and v[1] < 7)):
            log(LogLevel.Fatal, "This software requires at least Sqlite version 3.7.0!")
            exit(1)

        log(LogLevel.Info, "Opening database connection.")

        self.conn = sqlite3.connect('world.db')
        active = True

        c = self.conn.cursor()
        c.execute('PRAGMA foreign_keys = ON')

        # Get list of tables
        c.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = c.fetchall()
        if len(tables) == 0: log(LogLevel.Info, "Initializing empty database...")

        if not ('meta',) in tables:
            log(LogLevel.Info, '- Creating meta table...')
            c.execute("""CREATE TABLE meta (
                    key TEXT PRIMARY KEY ASC,
                    value NONE
                    )""")
            c.execute("""INSERT INTO meta VALUES ('schema_version', 0)""")

        if not ('objects',) in tables:
            log(LogLevel.Info, '- Creating objects table...')
            c.execute("""CREATE TABLE objects (
                    id INTEGER PRIMARY KEY ASC,   -- Primary database ID of this object
                    parent INTEGER NOT NULL,      -- Parent of this object
                    owner INTEGER NOT NULL,       -- Owner of this object
                    name TEXT NOT NULL,           -- Name of the object
                    type INTEGER NOT NULL,        -- Type of the object (Room=0, Player=1, Item=2, Action=3, Script=4)
                    flags INTEGER NOT NULL,       -- Object flags
                    link INTEGER,                 -- Link to another object
                    desc TEXT,                    -- Object description
                    FOREIGN KEY(link) REFERENCES objects(id),
                    FOREIGN KEY(parent) REFERENCES objects(id),
                    FOREIGN KEY(owner) REFERENCES objects(id),
                    CHECK( type >= 0 AND type <= 4 )
                    )""")

            log(LogLevel.Info, '-- Creating initial database objects...')
            # Create Room #0 (Universe) and Player #1 (God)
            t = [(0, 0, 0, 'The Universe', 0, 0, None, "The Universe is a mysterious place that contains all other things."),
                 (1, 0, 1, 'God', 1, 0, 0, None),
                 (2, 1, 1, 'no tea', 2, 0, 1, None),
                 (3, 0, 1, 'west', 3, 0, 0, "You gaze off to the west, if that is in fact west... it's hard to tell when you're in space.")]

            c.executemany("""INSERT INTO objects VALUES(?,?,?,?,?,?,?,?)""", t)
            # Set Room #0's owner as God
            c.execute("""UPDATE objects SET owner=1 WHERE id=0""")


        # Create users table if it does not exist
        if not ('users',) in tables:
            log(LogLevel.Info, '- Creating users table...')
            c.execute("""CREATE TABLE users (
                    username TEXT,
                    password TEXT,
                    salt TEXT,
                    email TEXT,
                    obj INTEGER,
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")

            # Create admin user
            log(LogLevel.Info, '-- Creating admin user...')
            pwhash, salt = self.create_hash('admin')
            t = ('admin', pwhash, salt, 'admin@localhost', 1)
            c.execute("""INSERT INTO users VALUES (?, ?, ?, ?, ?)""", t)

        if not ('deleted',) in tables:
            log(LogLevel.Info, '- Creating deleted table...')
            c.execute("""CREATE TABLE deleted (obj INTEGER, FOREIGN KEY(obj) REFERENCES object(id))""")

        if not ('inventory',) in tables:
            log(LogLevel.Info, '- Creating inventory table...')
            c.execute("""CREATE TABLE inventory (
                    child INTEGER UNIQUE,
                    parent INTEGER,
                    FOREIGN KEY(child) REFERENCES objects(id),
                    FOREIGN KEY(parent) REFERENCES objects(id)
                    )""")

        if not ('locks',) in tables:
            log(LogLevel.Info, '- Creating locks table...')
            c.execute("""CREATE TABLE locks (
                    obj INTEGER,
                    lock INTEGER,
                    FOREIGN KEY(obj) REFERENCES objects(id),
                    FOREIGN KEY(lock) REFERENCES objects(id)
                    )""")

        if not ('acl',) in tables:
            log(LogLevel.Info, '- Creating acl table...')
            c.execute("""CREATE TABLE acl (
                    obj INTEGER,
                    player INTEGER,
                    flags INTEGER,
                    FOREIGN KEY(obj) REFERENCES objects(id),
                    FOREIGN KEY(player) REFERENCES objects(id)
                    )""")

        if not ('messages',) in tables:
            log(LogLevel.Info, '- Creating messages table...')
            c.execute("""CREATE TABLE messages (
                    obj INTEGER,
                    succ TEXT,
                    fail TEXT,
                    osucc TEXT,
                    ofail TEXT,
                    'drop' TEXT,
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")

        if not ('data',) in tables:
            log(LogLevel.Info, '- Creating data table...')
            c.execute("""CREATE TABLE data (
                    obj INTEGER,
                    props TEXT,
                    script TEXT,
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")

        log(LogLevel.Info, 'Rebuilding inventory table...')
        c.execute("""DELETE FROM inventory""")
        c.execute("""INSERT INTO inventory (child, parent)
        SELECT id, parent FROM objects""")

        self.conn.commit()

        c.close()

        log(LogLevel.Info, 'Database initialized.')

    def close(self):
        global active
        log(LogLevel.Info, "Closing database connection.")
        self.conn.close()
        active = False

    def load_object(self, world, obj):
        """Loads and returns an object out of the database."""
        if not active: raise DatabaseNotConnected()
        c = self.conn.cursor()
        c.execute("""SELECT id, parent, owner, name, type, flags, link, desc FROM objects WHERE id==?""", (obj,))
        result = c.fetchone()
        c.close()

        log(LogLevel.Debug, "We loaded {1}#{0} (type={2}) out of the database!".format(result[0], result[3], DBType(result[4])))

        obtype = result[4]
        if obtype == DBType.Room:
            newobj = Room(world, *result)
        elif obtype == DBType.Player:
            newobj = Player(world, *result)
        elif obtype == DBType.Item:
            newobj = Item(world, *result)
        elif obtype == DBType.Action:
            newobj = Action(world, *result)
        elif obtype == DBType.Script:
            newobj = Script(world, *result)
        else:
            newobj = None

        log(LogLevel.Debug, "Returning {0}".format(repr(newobj)))
        return newobj

    def save_object(self, thing):
        """Saves a modified object back to the database."""

        # Nothing to do here
        if not thing.dirty: return

        c = self.conn.cursor()
        c.execute("""UPDATE objects SET parent=?, owner=?, name=?, flags=?, link=?, desc=? WHERE id==?""",
                (thing.parent_id(), thing.owner_id(), thing.name(), thing.flags(), thing.link_id(), thing.desc(), thing.id()))
        c.close()

        thing.dirty = False

    def get_contents(self, obj):
        if not active: raise DatabaseNotConnected()
        c = self.conn.cursor()
        c.execute("""SELECT child FROM inventory WHERE parent==?""", (obj,))
        results = c.fetchall()
        c.close()

        return tuple(map(lambda x:x[0], results))

    def get_new_id(self):

        pass

if __name__ == '__main__':
    d = Database()
    
    log(LogLevel.Info, "Test successful password check: " + repr(d.check_pass('admin', 'admin')))
    log(LogLevel.Info, "Test failed password check: " + repr(d.check_pass('admin', 'wrongpass')))

    d.close()
