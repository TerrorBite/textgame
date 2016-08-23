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
            c.execute("""
CREATE TABLE IF NOT EXISTS meta (
    -- Stores metadata about the database, such as schema version number.
    -- This data is stored as simple key-value pairs.

    key TEXT PRIMARY KEY ASC,   -- Key name
    value NONE                  -- Value, can be any type
)
                    """)
            c.execute("""INSERT INTO meta VALUES ('schema_version', 0)""")
            log(LogLevel.Info, '- Created meta table.')

        # This table stores basic data about an object.
        # Extended data is stored in a separate table. This is done in order to
        # make it faster to do basic queries about an object.
        if 'objects' not in tables:
            c.execute("""
CREATE TABLE IF NOT EXISTS objects (
    -- This table stores basic data about an object.
    -- Extended data is stored in other tables, or as properties.
    -- This should make it faster to perform basic queries on an object.

    id INTEGER PRIMARY KEY ASC,       -- Primary database ID of this object (alias to built in rowid column)
    name TEXT NOT NULL,               -- Name of the object
    type INTEGER NOT NULL,            -- Type of the object (Room=0, Player=1, Item=2, Action=3, Script=4)
    flags INTEGER NOT NULL,           -- Bitfield of object flags
    parent INTEGER NOT NULL,          -- ID of the parent object (i.e. location) of this object
    owner INTEGER NOT NULL,           -- ID of owner of this object
    link INTEGER DEFAULT NULL,        -- Link to another object (home, or action). Null if unlinked.
    money INTEGER DEFAULT 0 NOT NULL, -- Amount of currency that this object contains
                                      -- The following timestamps are in unix time:
    created INTEGER DEFAULT (strftime('%s','now')),  -- Time of creation
    modified INTEGER DEFAULT (strftime('%s','now')), -- Time last modified in any way
    lastused INTEGER DEFAULT (strftime('%s','now')), -- Time last used (without modifying it)
    desc TEXT,                        -- Object description - this field is deprecated

    FOREIGN KEY(parent) REFERENCES objects(id),
    FOREIGN KEY(owner) REFERENCES objects(id),
    FOREIGN KEY(link) REFERENCES objects(id),

    -- Enforce the four possible types of object.
    CHECK( type >= 0 AND type <= 4 )
)
                    """)
            log(LogLevel.Info, '- Created objects table.')
            c.execute("""CREATE INDEX IF NOT EXISTS parent_index ON objects(parent)
    -- Contents of an object is determined by finding all objects whose parent is the container.""")
            c.execute("""CREATE INDEX IF NOT EXISTS owner_index ON objects(owner)
    -- Allow looking up or filtering objects by owner.""")
            c.execute("""CREATE INDEX IF NOT EXISTS link_index ON objects(link)
    -- Allow looking up or filtering objects by link - is this needed?""")

            # Create Room #0 (Universe) and Player #1 (Creator)
            # Initially create "The Universe" as owning itself, due to constraints
            now = time.time()

            #     id  name           typ flg par own link  $  cre. mod. used desc
            t = [(0, 'The Universe',  0,  0,  0,  0, None, 0, now, now, now, None), # desc fields here are now deprecated
                 (1, 'The Creator',   1,  0,  0,  1, None, 0, now, now, now, None),
                 # Other test objects
                 (2, 'no tea',        2,  0,  1,  1,  1,   0, now, now, now, None),
                 (3, 'west',          3,  0,  0,  1,  0,   0, now, now, now, None),
                 (4, 'drink',         3,  0,  2,  1,  0,   0, now, now, now, None),
                ]
            c.executemany("""INSERT INTO objects VALUES(?,?, ?,?,?,?,?, ?, ?,?,?, ?)""", t)
            # Set Room #0's owner as God
            c.execute("""UPDATE objects SET owner=1 WHERE id=0""")
            log(LogLevel.Info, '-- Created initial database objects.')

        # Create users table if it does not exist
        if 'users' not in tables:
            c.execute("""
CREATE TABLE IF NOT EXISTS users (
    -- Stores login information about user accounts.

    username TEXT PRIMARY KEY,  -- Username (is primary key)
    password TEXT,              -- Password hash (hexadecimal)
    salt TEXT,                  -- Salt used in hash (hexadecimal)
    email TEXT,                 -- Email address
    obj INTEGER,                -- Character reference
    -- Note: In future, the "obj" field will be removed and a separate table
    -- created which allows each account to have multiple characters associated.

    FOREIGN KEY(obj) REFERENCES objects(id)
)
                    """)

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
            c.execute("""
CREATE TABLE IF NOT EXISTS props (
    -- Stores arbitrary properties about an object.
    -- This is essentially a set of key/value pairs associated with an object.
    -- Each row holds a single key/value pair.
    -- At a database level, key names are arbitrary, but the server uses a
    -- directory structure maintained using a naming convention for the keys.

    obj INTEGER,        -- ID of object
    key TEXT,           -- Name of this property
    value TEXT,         -- Value of this property

    FOREIGN KEY(obj) REFERENCES objects(id)
)
                    """)
            # Index by id and key, unique index to ensure an id-key pairing cannot exist twice.
            c.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS key_index ON props(
    obj, key -- Properties are uniquely indexed by id-key pairing.
    -- This constraint ensures that an object cannot have the same key twice,
    -- which ensures our INSERT OR REPLACE statement will work correctly.
)
                    """)

            # Assign sample property values to our starting objects.
            t=[ (0, '_/desc', "You can't hear anything, see anything, smell anything, feel anything, or taste anything, and you do not even know where you are or who you are or how you got here."),
                (1, '_/desc', "The being that you see cannot be described."),
                (2, '_/desc', "You really wish you had a cup of tea right about now."),
                (3, '_/desc', "There's nothing exciting in that direction."),
                (3, '_/succ', "Life is peaceful there..."),
                (3, '_/fail', "The way is closed."),
                (4, '_/fail', "You can't drink tea that you don't have."),
              ]
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
            c.execute("""
CREATE TABLE IF NOT EXISTS deleted (
    -- This single-column table allows objects to be marked as deleted.
    -- This allows ID values to be reused.
    -- It also potentially allows recycled objects to be recovered.

    obj INTEGER, -- The ID of a deleted object

    FOREIGN KEY(obj) REFERENCES object(id)
)
                    """)
            log(LogLevel.Info, '- Created deleted IDs table.')

        # Many-to-many table for locks
        if 'locks' not in tables:
            c.execute("""
CREATE TABLE IF NOT EXISTS locks (
    -- This many-to-many table contains basic locks for objects.

    obj INTEGER,  -- ID of the object.
    lock INTEGER, -- ID of an object that has a lock on this object.

    FOREIGN KEY(obj) REFERENCES objects(id),
    FOREIGN KEY(lock) REFERENCES objects(id)
)
                    """)
            log(LogLevel.Info, '- Created locks table.')

        # Many-to-many table for access control list entries
        if 'acl' not in tables:
            c.execute("""
CREATE TABLE IF NOT EXISTS acl (
    -- This many-to-many table contains Access Control List entries.

    obj INTEGER,     -- ID of the object to which access is being controlled.
    player INTEGER,  -- ID of a player object which has some degree of access.
    flags INTEGER,   -- Flags which describe what degree of access is allowed.

    FOREIGN KEY(obj) REFERENCES objects(id),
    FOREIGN KEY(player) REFERENCES objects(id)
)
                    """)
            log(LogLevel.Info, '- Created acl table.')

        if 'scripts' not in tables:
            c.execute("""
CREATE TABLE IF NOT EXISTS scripts (
    -- This table stores the executable content of scripts.

    obj INTEGER,    -- ID of script object
    type INTEGER,   -- Type of script (0=lua)
    script TEXT,    -- Script content

    FOREIGN KEY(obj) REFERENCES objects(id)
)
                    """)
            log(LogLevel.Info, '- Created scripts table.')

        if not cursor: c.close()
    # end create_schema()

    def _db_save_object(self, thing):
        """
        Save basic properties of an object to the database. The object must already exist.
        """
        #NOTE: Should database drivers have ANY knowledge about Things?
        with Cursor(self) as c:
            # Note: Will fail if the row being updated does not match the dbtype of the Thing provided.
            #NOTE: Should we use INSERT OR REPLACE INTO instead?
            c.execute("""UPDATE objects SET parent=?, owner=?, name=?, flags=?, link=?, money=?, modified=?, lastused=?, desc=? WHERE id==? AND type==?""",
                    (thing.parent.id, thing.owner.id, thing.name, thing.flags, thing.link.id if thing.link else None,
                        thing.money, thing.modified, thing.lastused, thing.desc, thing.id, int(thing.dbtype)))
            #c.execute("""UPDATE messages SET succ=?, fail=?, osucc=?, ofail=?, 'drop'=? WHERE obj==?""",
            #        (thing.desc, thing.succ, thing.fail, thing.osucc, thing.ofail, thing.drop, thing.id))

    def _db_load_object(self, obj):
        """
        Load object out of the database.
        """
        with Cursor(self) as c:
            c.execute("""SELECT type, name, flags, parent, owner, link, money, created, modified, lastused FROM objects WHERE id==?""", (obj,))
            return c.fetchone()

    def _db_get_contents(self, obj):
        """
        Returns a list of database IDs of objects contained by this object.
        """
        with Cursor(self) as c:
            c.execute("""SELECT id FROM objects WHERE parent==?""", (obj,))
            return tuple(map(lambda x:x[0], c.fetchall()))

    def _db_get_property(self, obj, key):
        """
        Fetches a property of an object.
        """
        with Cursor(self) as c:
            c.execute("""SELECT value FROM props WHERE obj==? AND key==?""", (obj, key))
            result = c.fetchone()
            return result[0] if result else None

    def _db_set_property(self, obj, key, value):
        """
        Writes a property of an object.
        """
        with Cursor(self) as c:
            c.execute("""INSERT OR REPLACE INTO props VALUES (?, ?, ?)""", (obj, key, value))

    def _db_get_user(self, username):
        """
        Fetches user account info from the database.
        """
        #TODO: Upgrade to multiple characters per account
        with Cursor(self) as c:
            c.execute("SELECT password, salt, obj FROM users WHERE username == ?", (username,))
            return c.fetchone()

    def _db_get_available_id(self):
        with Cursor(self) as c:
            c.execute("SELECT obj FROM deleted ORDER BY obj ASC LIMIT 1")
            result = c.fetchone()
            return result[0] if result else None # TODO

    def _db_create_new_object(self, dbtype, name, parent, owner):
        with Cursor(self) as c: 
            c.execute("""BEGIN""")
            c.execute("SELECT obj FROM deleted ORDER BY obj ASC LIMIT 1")
            obj = c.fetchone() # If obj is None, Sqlite will use the next available ID
            c.execute(
            """INSERT OR REPLACE INTO objects(id, name, type, flags, parent, owner)"""\
                                   """VALUES (?,  ?,    ?,    0,     ?,      ?    )""",
                    obj, name, dbtype, parent, owner )
            # if obj is not present in deleted, this will do nothing
            c.execute("""DELETE FROM deleted WHERE id = ?""", obj)
            c.execute("""COMMIT""")
            return c.lastrowid            

