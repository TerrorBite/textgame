"""
Internal module for textgame.db

This module defines IDatabaseBackend
"""

# Third party library imports
from typing import Optional

from zope.interface import Interface


class IDatabaseBackend(Interface):
    """
    This interface should be implemented by a class which knows how to
    communicate with a particular type of database. For example: SQLite,
    MariaDB, or PostgreSQL.
    """

    def __init__(connect_string: str):
        """
        Creates this database instance. Should connect to the database when it is called.

        The connect_string is an implementation-specific string which tells the instance
        how to connect to the desired database. For SQLite, this might just be the filename
        of the database file. For other engines, this string might be in the form
        "username:password@hostname:port". The string that is passed in will be provided
        directly from a config file where the admin can put any string they need to.
        """

    def close():
        """
        Cleanly close the database connection.

        After this is called, the instance is not expected to be usable.
        """

    def get_user(username):
        """
        Given a username, this method returns a record from the User table if the user
        exists, and None otherwise.
        """

    def set_password(username: str, password: bytes, salt: bytes):
        """
        This method should take a username, a hashed password, and a salt, and store them for that username.

        If the username does not exist, it should be created.
        """

    def create_character(username: str, character: str) -> Optional[int]:
        """
        This method should create a character in the Characters table for the given username, and then return
        the database ID of the newly created character.

        If the character already exists for this username, this method should do nothing and return None.
        """

    def get_user_characters(username):
        """
        Given a username, this method returns a list of character
        names associated with a username.
        """

    def get_player_id(username, charname):
        """
        Given a username and a character name, this method returns the
        id of the matching Player record from the Things table if the
        character exists. If it does not exist, None is returned.
        """

    def get_property(obj, key):
        """
        This method should return the value of the property named "key" on the object whose
        id is "obj".
        """

    def set_property(obj, key, val):
        """
        This method should set the value of the property named "key" on the object whose
        id is "obj" to the value "val".
        """

    def load_object(obj):
        """
        This method should load an object out of the database, returning the row loaded,
        with the fields in the following order:
        type, name, flags, parent, owner, link, money, created, modified, lastused
        """


def find_backends():
    """
    This function locates classes within the "backends" package
    which claim to implement the IDatabaseBackend interface.

    It will return a list of those classes.
    """
    # TODO: First, load the backends


