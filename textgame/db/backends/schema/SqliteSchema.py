from textwrap import dedent
import time

class Schema(object):
    # Stores CREATE TABLE statements.
    tables = {

        "meta": """
            CREATE TABLE IF NOT EXISTS meta (
                -- Stores metadata about the database, such as schema version number.
                -- This data is stored as simple key-value pairs.

                key TEXT PRIMARY KEY ASC,   -- Key name
                value NONE                  -- Value, can be any type
            )""",

        "objects": """
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

                FOREIGN KEY(parent) REFERENCES objects(id),
                FOREIGN KEY(owner) REFERENCES objects(id),
                FOREIGN KEY(link) REFERENCES objects(id),

                -- Enforce the five possible types of object.
                CHECK( type >= 0 AND type <= 4 )
            )""",

        "users": """
            CREATE TABLE IF NOT EXISTS users (
                -- Stores login information about user accounts.

                username TEXT PRIMARY KEY,  -- Username (is primary key)
                password TEXT,              -- Password hash (hexadecimal)
                salt TEXT,                  -- Salt used in hash (hexadecimal)
                email TEXT                  -- Email address

            )""",

        "characters": """
            CREATE TABLE IF NOT EXISTS characters (
                -- Pairs a character to a user account.

                username TEXT,              -- Username that owns this character
                obj INTEGER,                -- Reference to the Player object of the character

                FOREIGN KEY(username) REFERENCES users(username),
                FOREIGN KEY(obj) REFERENCES objects(id)
            )""",
        
        "properties": """
            CREATE TABLE IF NOT EXISTS properties (
                -- Stores arbitrary properties about an object.
                -- This is essentially a set of key/value pairs associated with an object.
                -- Each row holds a single key/value pair.
                -- At a database level, key names are arbitrary, but the server uses a
                -- directory structure maintained using a naming convention for the keys.

                obj INTEGER,        -- ID of object
                key TEXT,           -- Name of this property
                value TEXT,         -- Value of this property

                FOREIGN KEY(obj) REFERENCES objects(id)
            )""",

        "deleted": """
            CREATE TABLE IF NOT EXISTS deleted (
                -- This single-column table allows objects to be marked as deleted.
                -- This allows ID values to be reused.
                -- It also potentially allows recycled objects to be recovered.

                obj INTEGER, -- The ID of a deleted object

                FOREIGN KEY(obj) REFERENCES object(id)
            )""",
        
        "locks": """
            CREATE TABLE IF NOT EXISTS locks (
                -- This many-to-many table contains basic locks for objects.

                obj INTEGER,  -- ID of the object.
                lock INTEGER, -- ID of an object that has a lock on this object.

                FOREIGN KEY(obj) REFERENCES objects(id),
                FOREIGN KEY(lock) REFERENCES objects(id)
            )""",
            
        "acls": """
            CREATE TABLE IF NOT EXISTS acl (
                -- This many-to-many table contains Access Control List entries.

                obj INTEGER,     -- ID of the object to which access is being controlled.
                player INTEGER,  -- ID of a player object which has some degree of access.
                flags INTEGER,   -- Flags which describe what degree of access is allowed.

                FOREIGN KEY(obj) REFERENCES objects(id),
                FOREIGN KEY(player) REFERENCES objects(id)
            )""",
        
        "scripts": """
            CREATE TABLE IF NOT EXISTS scripts (
                -- This table stores the executable content of scripts.

                obj INTEGER,    -- ID of script object
                type INTEGER,   -- Type of script (0=lua)
                script TEXT,    -- Script content

                FOREIGN KEY(obj) REFERENCES objects(id)
            )"""
    }

    indices = {
        "objects": ("""
                CREATE INDEX IF NOT EXISTS parent_index ON objects(parent)
                    -- Contents of an object are determined by finding
                    -- all objects whose parent is the container.
            """, """
                CREATE INDEX IF NOT EXISTS owner_index ON objects(owner)
                    -- Allow looking up or filtering objects by owner.
            """, """
                CREATE INDEX IF NOT EXISTS link_index ON objects(link)
                    -- Allow looking up or filtering objects by link - is this needed?
            """),
        
        "properties": ("""
                CREATE UNIQUE INDEX IF NOT EXISTS key_index ON properties(obj, key)
                    -- Properties are uniquely indexed by id-key pairing.
                    -- This constraint ensures that an object cannot have the same key twice,
                    -- which ensures our INSERT OR REPLACE statement will work correctly.
            """,)
    }

    # This is a tuple, each item is a tuple of SQL statements.
    upgrades = (
        # Upgrade to Schema 1
        (   "ALTER TABLE objects ADD health INTEGER",
            "ALTER TABLE props RENAME TO properties"
        )
    )

    def __init__(self, cursor):
        self.cursor = cursor


    def _create_table(self, tablename, values=[]):
        # Execute CREATE TABLE statement
        self.cursor.execute( dedent( self.tables[tablename] ).strip() )

        if tablename in self.indices:
            # Create any indexes that this table has.
            for item in self.indices[tablename]:
                self.cursor.execute( dedent(item).strip() )

        if len(values) > 0:
            # Make some question marks separated by commas.
            qmarks = ','.join( ["?"] * len(values[0]) )
            # Create insert statement.
            insert = "INSERT OR IGNORE INTO {0} VALUES({1})".format( tablename, qmarks )
            # Execute insert statement.
            self.cursor.executemany( insert, values )

    def create(self):
        # Meta table.
        self._create_table( "meta", [('schema_version', 0)] )

        # 0: Universal parent room (has to be created owning itself due to constraints)
        # 1: Admin player
        now = time.time()
        self._create_table( "objects", [
        #    id  name           typ flg par own link  $  cre. mod. used
            (0, 'The Universe',  0,  0,  0,  0, None, 0, now, now, now),
            (1, 'The Creator',   1,  0,  0,  1, None, 0, now, now, now),
            # Other test objects (for testing)
            (2, 'no tea',        2,  0,  1,  1,  1,   0, now, now, now),
            (3, 'west',          3,  0,  0,  1,  0,   0, now, now, now),
            (4, 'drink',         3,  0,  2,  1,  0,   0, now, now, now),
        ] )

        # Update the universal room so that the admin player owns it
        self.cursor.execute("""UPDATE objects SET owner=1 WHERE id=0""")

        # Properties table
        self._create_table( "properties", [
            (0, '_/desc', "You can't hear anything, see anything, smell anything, " +
                "feel anything, or taste anything, and you do not even know " +
                "where you are or who you are or how you got here."),
            (1, '_/desc', "The being that you see cannot be described."),
            (2, '_/desc', "You really wish you had a cup of tea right about now."),
            (3, '_/desc', "There's nothing exciting in that direction."),
            (3, '_/succ', "Life is peaceful there..."),
            (3, '_/fail', "The way is closed."),
            (4, '_/fail', "You can't drink tea that you don't have.")
        ])

        # Users table etc
        for table in "users characters locks acls scripts deleted".split():
            self._create_table( table )

    def upgrade(self):
        """
        Upgrades the database to the latest schema version.
        """
        # What is the current schema version of the database?
        self.cursor.execute("SELECT value FROM meta WHERE key='schema_version'")
        current = int( self.cursor.fetchone()[0] )
        upgrades = self.upgrades[current:]
        for upgrade in upgrades:
            log.info( "Upgrading schema: {0} => {1}".format( current, current+1 ) )
            try:
                with cursor.connection:
                    for statement in upgrade:
                        self.cursor.execute( statement )
                    current += 1
                    self.cursor.execute( "REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (current,) )
            except sqlite3.IntegrityError:
                pass
    
    def get_tables(self):
        self.cursor.execute("""SELECT name FROM sqlite_master WHERE type='table'""")
        return [str(x[0]) for x in c.fetchall()]
