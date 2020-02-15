"""
This module is the Sqlite implementation of the textgame database.
"""

import sqlite3

# Third party library imports
import time

from zope.interface import implementer
from packaging import version

from textgame.db import IDatabaseBackend
from textgame.db.backends.schema.SqliteSchema import Schema
from textgame.Util import log


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


@implementer(IDatabaseBackend)
class Sqlite(object):
    def __init__(self, connect_string):
        self.filename = connect_string
        log.info("Database activated: " + connect_string)

        # Sanity check sqlite version 3.6.19 or greater
        sqlite_version = version.parse(sqlite3.sqlite_version)
        if sqlite_version < version.parse("3.24.0"):
            log.warn("Sqlite backend needs a newer version of Sqlite.")
            log.warn("You have: Sqlite {0}".format(sqlite3.sqlite_version))
            log.warn("You need: Sqlite 3.6.19 or later")
            log.warn("Continuing anyway, but foreign key constraints will not work.")

        log.info("Opening sqlite database connection.")

        self.conn = sqlite3.connect(connect_string)
        self.active = True
        c = self.conn.cursor()
        c.execute('PRAGMA foreign_keys = ON')

        Schema(c).create()
        c.close()
        self.conn.commit()
        pass

    def close(self):
        """
        Closes the Sqlite database.
        """
        self.conn.commit()
        self.conn.close()

    def get_user(self, username):
        """
        Return a row from the User table, or None.
        """
        with Cursor(self) as c:
            c.execute("SELECT password, salt FROM users WHERE username == ?", (username,))
            return c.fetchone()

    def set_password(self, username: str, password_hash: bytes, salt: bytes):
        with Cursor(self) as c:
            # c.execute("UPDATE users SET password=?, salt=? WHERE username=?", (password_hash, salt, username))
            c.execute("INSERT INTO users(username, password, salt) VALUES (?, ?, ?) "
                      "ON CONFLICT(username) DO UPDATE SET password=?, salt=? WHERE username=?",
                      (username, password_hash, salt, password_hash, salt, username))
        return

    def get_user_characters(self, username):
        """
        Given a username, this method returns a list of character
        names associated with a username.
        """
        with Cursor(self) as c:
            c.execute("SELECT DISTINCT name FROM objects INNER JOIN characters "
                      "ON characters.obj == objects.id "
                      "AND characters.username == ?", (username,))
            return [row[0] for row in c.fetchall()]

    def create_character(self, username, charname):
        """
        Given a username and a character name, this method creates a
        new Player object and returns the id of the created object. If
        the provided character name is already in use, the object is not
        created, and None is returned.

        :param username: The username which the character will belong to. No check
            is done to ensure that the username exists.
        :param charname: The name of the character to create.
        :return: The ID of the new character, or None if it could not be created.
        """
        with Cursor(self) as c:
            # First, create the Player. This will fail (due to database constraints) if the name is in use.
            now = time.time()
            new_character_room = 0
            try:
                c.execute("INSERT INTO objects VALUES (NULL, ?, 1, 0, ?, 1, NULL, 0, ?, ?, ?) ON CONFLICT ABORT",
                          (charname, new_character_room, now, now, now)
                          )
                obj_id = c.lastrowid
                c.execute("UPDATE objects SET owner=? WHERE id=?", (obj_id, obj_id))
                c.execute("INSERT INTO characters VALUES (?, ?)", (username, charname))
            except sqlite3.IntegrityError:
                return None

    def get_player_id(self, username, charname):
        """
        Given a username and a character name, this method returns the
        id of the matching Player record from the Things table if the
        character exists. If it does not exist, None is returned.
        """
        with Cursor(self) as c:
            c.execute("SELECT id FROM objects INNER JOIN characters ON characters.obj == objects.id "
                      "AND characters.username == ? AND objects.name == ?", (username, charname))
            return c.fetchone()[0]

    def get_property(self, obj, key):
        """
        This method returns the value of the property named "key"
        on the object whose id is "obj".
        """
        with Cursor(self) as c:
            c.execute("""SELECT value FROM properties WHERE obj==? AND key==?""", (obj, key))
            result = c.fetchone()
            return result[0] if result else None

    def set_property(self, obj, key, val):
        """
        This method sets the value of the property named "key" on
        the object whose id is "obj" to the value "val".
        """
        with Cursor(self) as c:
            c.execute("""INSERT OR REPLACE INTO properties VALUES (?, ?, ?)""", (obj, key, val))

    def load_object(self, obj):
        with Cursor(self) as c:
            c.execute("SELECT type, name, flags, parent, owner, link, money, "
                      "created, modified, lastused FROM objects WHERE id==?", (obj,))
            return c.fetchone()

    def save_object(self, thing):
        # NOTE: Should database drivers have ANY knowledge about Things?
        with Cursor(self) as c:
            # Note: Will fail if the row being updated does not match the dbtype of the Thing provided.
            # NOTE: Should we use INSERT OR REPLACE INTO instead?
            c.execute("UPDATE objects SET parent=?, owner=?, name=?, flags=?, link=?, money=?,"
                      "modified=?, lastused=?, desc=? WHERE id==? AND type==?",
                      (thing.parent.id, thing.owner.id, thing.name, thing.flags, thing.link.id if thing.link else None,
                       thing.money, thing.modified, thing.lastused, thing.desc, thing.id, int(thing.dbtype)))

    def get_contents(self, obj):
        """
        Returns a list of database IDs of objects contained by this object.
        """
        with Cursor(self) as c:
            c.execute("""SELECT id FROM objects WHERE parent==?""", (obj,))
            return tuple(map(lambda x: x[0], c.fetchall()))

    def create_user(self, username, password, pubkeys):
        raise NotImplementedError()
