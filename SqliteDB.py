import Database
import sqlite3, time
from Util import log, LogLevel

class Cursor(object):
    """
    Used in a "with" statement to provide a cursor that is automatically closed.
    """
    def __init__(self, db):
        """
        Save the sqlite3 object from the SqliteDatabase
        """
        self.conn = db.conn

    def __enter__(self):
        """
        Obtain a cursor, save and return it.
        """
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, typ, value, traceback):
        """
        Close the cursor that we returned earlier.
        """
        self.cursor.close()

class SqliteDatabase(Database.Database):
    """
    This is an implementation of the Database class that uses Sqlite as the database backend.
    """
    
    def __init__(self):
        # Sanity check sqlite version 3.6.19 or greater
        v = sqlite3.sqlite_version_info
        if(v[0] < 3 or (v[0] == 3 and (v[1] < 6 or v[1] == 6 and v[2] < 19) ) ):
            log(LogLevel.Warn, "Sqlite backend needs a newer version of Sqlite.")
            log(LogLevel.Warn, "You have: Sqlite {0[0]}.{0[1]}.{0[2]}".format(v))
            log(LogLevel.Warn, "You need: Sqlite 3.6.19 or later")
            log(LogLevel.Warn, "Continuing anyway, but foreign key constraints will not work.")

        log(LogLevel.Info, "Opening sqlite database connection.")

        self.conn = sqlite3.connect('world.db')
        self.active = True
        c = self.conn.cursor()
        c.execute('PRAGMA foreign_keys = ON')
        
        self._db_create_schema(c)
        c.close()
        self.conn.commit()
    
    def _cursor(self):
        return Cursor(self.conn.cursor())

    def _db_close(self):
        self.conn.commit()
        self.conn.close()

    def _db_create_schema(self, cursor=None):
        """
        Create tables as required.
        """

        c = cursor if cursor else self.conn.cursor()

        # Obtain list of tables
        c.execute("""SELECT name FROM sqlite_master WHERE type='table'""")
        tables = [str(x[0]) for x in c.fetchall()]
        log(LogLevel.Debug, repr(tables))

        # The "meta" table is a simple key-value table that stores metadata about the database.
        if 'meta' not in tables:
            c.execute("""-- Stores metadata about the database, such as schema version number.
                    CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY ASC,
                    value NONE
                    )""")
            c.execute("""INSERT INTO meta VALUES ('schema_version', 0)""")
            log(LogLevel.Info, '- Created meta table.')

        # This table stores basic data about an object.
        # Extended data is stored in a separate table. This is done in order to
        # make it faster to do basic queries about an object.
        if 'objects' not in tables:
            c.execute("""-- This table stores basic data about an object.
                    -- Extended data is stored in other tables, or as properties.
                    -- This should make it faster to perform basic queries on an object.
                    CREATE TABLE IF NOT EXISTS objects (
                    id INTEGER PRIMARY KEY ASC,     -- Primary database ID of this object (alias to built in rowid column)
                    name TEXT NOT NULL,             -- Name of the object
                    type INTEGER NOT NULL,          -- Type of the object (Room=0, Player=1, Item=2, Action=3, Script=4)
                    flags INTEGER NOT NULL,         -- Object flags
                    parent INTEGER NOT NULL,        -- Parent (location) of this object
                    owner INTEGER NOT NULL,         -- Owner of this object
                    link INTEGER,                   -- Link to another object (home, or action)
                    money INTEGER,                  -- Amount of currency that this object contains
                    created INTEGER,                -- Timestamp object was created (seconds since unix epoch)
                    modified INTEGER,               -- When the object was last modified in any way
                    lastused INTEGER,               -- When the object was last used (without modifying it)
                    desc TEXT,                      -- Object description
                    FOREIGN KEY(parent) REFERENCES objects(id), -- replaces "inventory" table
                    FOREIGN KEY(owner) REFERENCES objects(id),
                    FOREIGN KEY(link) REFERENCES objects(id),
                    CHECK( type >= 0 AND type <= 4 )
                    )""")
            log(LogLevel.Info, '- Created objects table.')
            c.execute("""CREATE INDEX IF NOT EXISTS parent_index ON objects(parent)""")
            c.execute("""CREATE INDEX IF NOT EXISTS owner_index ON objects(owner)""")
            c.execute("""CREATE INDEX IF NOT EXISTS link_index ON objects(link)""")

            # Create Room #0 (Universe) and Player #1 (God)
            # Initially create "The Universe" as owning itself, due to constraints
            #t = [(0, 0, 0, 'The Universe', 0, 0, None, "The Universe is a mysterious place that contains all other things."),
            #     (1, 0, 1, 'God', 1, 0, 0, None),
            #     # Other test objects
            #     (2, 1, 1, 'no tea', 2, 0, 1, None),
            #     (3, 0, 1, 'west', 3, 0, 0, "You gaze off to the west, if that is in fact west... it's hard to tell when you're in space.")]
            now = time.time()

            #     id  name           t  f  p  o  link  m  cre. mod. used
            t = [(0, 'The Universe', 0, 0, 0, 0, None, 0, now, now, now, "The Universe contains all other things."),
                 (1, 'God',          1, 0, 0, 1, None, 0, now, now, now, "What you see cannot be described."),
                 # Other test objects
                 (2, 'no tea',       2, 0, 1, 1, 1,    0, now, now, now, None),
                 (3, 'west',         3, 0, 0, 1, 0,    0, now, now, now, "You look to the west.")]

            c.executemany("""INSERT INTO objects VALUES(?,?, ?,?,?,?,?, ?, ?,?,?, ?)""", t)
            # Set Room #0's owner as God
            c.execute("""UPDATE objects SET owner=1 WHERE id=0""")
            log(LogLevel.Info, '-- Created initial database objects.')

        # Create users table if it does not exist
        if 'users' not in tables:
            c.execute("""-- Stores login information about user accounts.
                    CREATE TABLE IF NOT EXISTS users (
                    username TEXT, -- Username
                    password TEXT, -- Password hash
                    salt TEXT,     -- Salt used in hash
                    email TEXT,    -- Email address
                    obj INTEGER,   -- Character reference (TODO: Multiple characters)
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")

            log(LogLevel.Info, '- Created users table.')
            # Create admin user
            pwhash, salt = self.create_hash('admin')
            t = ('admin', pwhash, salt, 'admin@localhost', 1)
            c.execute("""INSERT INTO users VALUES (?, ?, ?, ?, ?)""", t)
            log(LogLevel.Info, '-- Created admin user.')

        #TODO: Obliterate messages table in favor of using properties
        # Stores extended data about an object, currently comprised of the following data:
        # - Object's long-form description (
#        if 'messages' not in tables:
#            c.execute("""CREATE TABLE IF NOT EXISTS messages (
#                    obj INTEGER,                  -- ID of object
#                    succ TEXT,                    -- Success message
#                    fail TEXT,                    -- Failure message
#                    osucc TEXT,                   -- External success message
#                    ofail TEXT,                   -- External failure message
#                    'drop' TEXT,                  -- Message when item is dropped or exit "drops" a player
#                    FOREIGN KEY(obj) REFERENCES objects(id)
#                    )""")
#            t = [(0, None, None, None, None, None),
#                 (1, None, None, None, None, None),
#                 (2, None, None, None, None, None),
#                 (3, "Life is peaceful there...", "The way is closed.", None, None, None)]
#            c.executemany("""INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)""", t)
#            log(LogLevel.Info, '- Created messages table.')

        # Table for storing arbitrary 'properties' about an object.
        if 'props' not in tables:
            c.execute("""-- Stores arbitrary properties about an object.
                    -- This is essentially a set of key/value pairs associated with an object.
                    -- Each row holds a single key/value pair.
                    -- At a database level, key names are arbitrary, but the server uses a
                    -- directory structure maintained using a naming convention for the keys.
                    CREATE TABLE IF NOT EXISTS props (
                    obj INTEGER,        -- ID of object
                    key TEXT,           -- Name of this property
                    value TEXT,         -- Value of this property
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")
            # Index by id and key, unique index to ensure an id-key pairing cannot exist twice.
            # This is important to allow our INSERT OR REPLACE statement to work.
            c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS key_index ON props(obj, key)""")
            t=[ (0, '_/desc', "The Universe contains all other things."),
                (3, '_/succ', "Life is peaceful there..."),
                (3, '_/fail', "The way is closed.")]
            c.executemany("""INSERT INTO props VALUES (?, ?, ?)""", t)
            log(LogLevel.Info, '- Created props table.')


        # Contains a list of IDs whose objects have been marked as deleted.
        # When a user requests deletion of an object, it is flagged as deleted,
        # and its ID is added to this table. This gives users a chance to undo.
        # When a new object is created, the first ID in this table (if any) is
        # removed and claimed as the ID of the new object.
        # The details of the deleted object with that ID are then overwritten
        # with those of the new object, and the old object is lost forever.
        # This system allows IDs to be reused and doesn't leave "holes" in the database.
        if 'deleted' not in tables:
            c.execute("""-- This simple table allows objects to be marked as deleted.
                    -- This allows ID values to be reused.
                    -- It also potentially allows recycled objects to be recovered.
                    CREATE TABLE IF NOT EXISTS deleted (obj INTEGER, FOREIGN KEY(obj) REFERENCES object(id))""")
            log(LogLevel.Info, '- Created deleted IDs table.')

        # Many-to-many table for locks
        if 'locks' not in tables:
            c.execute("""-- This many-to-many table contains basic locks for objects.
                    CREATE TABLE IF NOT EXISTS locks (
                    obj INTEGER,
                    lock INTEGER,
                    FOREIGN KEY(obj) REFERENCES objects(id),
                    FOREIGN KEY(lock) REFERENCES objects(id)
                    )""")
            log(LogLevel.Info, '- Created locks table.')

        # Many-to-many table for access control list entries
        if 'acl' not in tables:
            c.execute("""-- This many-to-many table contains Access Control List entries.
                    CREATE TABLE IF NOT EXISTS acl (
                    obj INTEGER,
                    player INTEGER,
                    flags INTEGER,
                    FOREIGN KEY(obj) REFERENCES objects(id),
                    FOREIGN KEY(player) REFERENCES objects(id)
                    )""")
            log(LogLevel.Info, '- Created acl table.')

        if 'scripts' not in tables:
            c.execute("""-- This table stores the executable content of scripts.
                    CREATE TABLE IF NOT EXISTS scripts (
                    obj INTEGER,                  -- ID of object
                    script TEXT,
                    FOREIGN KEY(obj) REFERENCES objects(id)
                    )""")
            log(LogLevel.Info, '- Created scripts table.')

        if not cursor: c.close()
    # end create_schema()

    def _db_save_object(self, thing):
        """
        Save an object to the database.
        """
        with Cursor(self) as c:
            c.execute("""UPDATE objects SET parent=?, owner=?, name=?, flags=?, link=?, money=?, modified=?, lastused=?, desc=? WHERE id==?""",
                    (thing.parent.id, thing.owner.id, thing.name, thing.flags, thing.link.id if thing.link else None,
                        thing.money, thing.modified, thing.lastused, thing.desc, thing.id))
            #c.execute("""UPDATE messages SET succ=?, fail=?, osucc=?, ofail=?, 'drop'=? WHERE obj==?""",
            #        (thing.desc, thing.succ, thing.fail, thing.osucc, thing.ofail, thing.drop, thing.id))

    def _db_load_object(self, obj):
        """
        Load object out of the database.
        """
        with Cursor(self) as c:
            c.execute("""SELECT name, type, flags, parent, owner, link, money, created, modified, lastused FROM objects WHERE id==?""", (obj,))
            return c.fetchone()

    def _db_get_contents(self, obj):
        """
        Returns a list of database IDs of objects contained by this object.
        """
        with Cursor(self) as c:
            c.execute("""SELECT id FROM objects WHERE parent==?""", (obj,))
            return tuple(map(lambda x:x[0], c.fetchall()))

    def _db_get_property(self, obj, key):
        with Cursor(self) as c:
            c.execute("""SELECT value FROM props WHERE obj==? AND key==?""", (obj, key))
            result = c.fetchone()
            return result[0] if result else None

    def _db_set_property(self, obj, key, value):
        with Cursor(self) as c:
            c.execute("""INSERT OR REPLACE INTO props VALUES (?, ?, ?)""", (obj, key, value))

    def _db_get_user(self, username):
        with Cursor(self) as c:
            c.execute("SELECT password, salt, obj FROM users WHERE username == ?", (username,))
            return c.fetchone()

