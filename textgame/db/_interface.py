"""
Internal module for textgame.db

This module defines IDatabaseBackend
"""

# Third party library imports
from zope.interface import Interface

class IDatabaseBackend(Interface):
    """
    This interface should be implemented by a class which knows how to
    communicate with a particular type of database. For example: SQLite,
    MariaDB, or PostgreSQL.
    """

    def __init__(self, connect_string):
        """
        Creates this database instance. Should connect to the database when it is called.

        The connect_string is an implementation-specific string which tells the instance
        how to connect to the desired database. For SQLite, this might just be the filename
        of the database file. For other engines, this string might be in the form
        "username:password@hostname:port". The string that is passed in will be provided
        directly from a config file where the admin can put any string they need to.
        """

    def close(self):
        """
        Cleanly close the database connection.

        After this is called, the instance is not expected to be usable.
        """

    def get_user(self, username):
        """
        Given a username, this method returns a record from the User table if the user
        exists, and None otherwise.
        """

    def create_user(self, username, password, pubkeys):
        """
        Creates a new user in the User table.
        """

    def get_user_characters(self, username):
        """
        Given a username, this method returns a list of character
        names associated with a username.
        """

    def get_player_id(self, username, charname):
        """
        Given a username and a character name, this method returns the
        id of the matching Player record from the Things table if the
        character exists. If it does not exist, None is returned.
        """

    def get_property(self, obj, key):
        """
        This method should return the value of the property named "key" on the object whose
        id is "obj".
        """

    def set_property(self, obj, key, val):
        """
        This method should set the value of the property named "key" on the object whose
        id is "obj" to the value "val".
        """

    def load_object(self, obj):
        """
        This method should load an object out of the database, returning the row loaded,
        with the fields in the following order:
        type, name, flags, parent, owner, link, money, created, modified, lastused
        """


