from textgame import Database
import sqlite3, time
from textgame.Util import log, LogLevel

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
        raise RuntimeError("Deprecated!")
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
        from textgame.db.backends.schema.SqliteSchema import Schema
        Schema(cursor).create()

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
            c.execute("SELECT password, salt FROM users WHERE username == ?", (username,))
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

