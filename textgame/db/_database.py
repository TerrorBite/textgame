"""
Internal module of textgame.db

This file provides the Database class and the DBType enum.
"""
from typing import Tuple, Sequence, Optional, Type

__all__ = ["Database", "DBType"]

# System imports
import hashlib
import struct
import random
import time
import functools
import types
from enum import Enum

from zope.interface import verify
from zope.interface.exceptions import Invalid

# Local imports
from textgame.db import backends, IDatabaseBackend
import textgame.Things
from textgame.Util import get_logger

logger = get_logger(__name__)


class DBType(Enum):
    """
    This is the master Enum of Thing types as used in the database.
    Do not re-order this, or existing databases will break!
    """
    Room = 0
    Player = 1
    Item = 2
    Action = 3
    Script = 4


# Attach dbtype to classes
for t in DBType:
    cls = getattr(textgame.Things, t.name)
    cls.dbtype = t
    t.type = cls


def _get_backends():
    modules = (m for k, m in vars(backends).items() if isinstance(m, types.ModuleType))
    classes = {cls for mod in modules for cls in vars(mod).values()
            if isinstance(cls, type) and IDatabaseBackend.implementedBy(cls)}

    # Validate classes
    for cls in tuple(classes):
        try:
            verify.verifyClass(IDatabaseBackend, cls)
        except Invalid as e:
            classes.remove(cls)
            logger.warning(f"Backend {cls!r} is not usable, it will not be available.")
            logger.warning(f"'{cls.__name__}' is not valid as a backend: {e!s}")
    if not classes:
        logger.critical("No database backends are available.")
    return {cls.__name__: cls for cls in classes}


def Thing_of_type(dbtype):
    """
    Given a DBType, returns the Thing class for that type.
    """
    return getattr(textgame.Things, dbtype.name)


class DatabaseNotConnected(Exception):
    pass


def require_connection(f):
    """
    Decorator for the Database class that will raise DatabaseNotConnected
    if the decorated method is called without the database connected.
    """
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        if not hasattr(self, "active"): self.active = False
        if not self.active: raise DatabaseNotConnected()
        return f(self, *args, **kwargs)
    return wrapper


def salt_to_bytes(salt: int) -> bytes:
    return salt.to_bytes(8, 'big', signed=True)


def hash_pass(password: str, salt: int) -> bytes:
    """
    Compute a password hash given a plaintext password and a binary salt value.

    This is currently derived using RSA PBKDF2 with 32768 rounds of HMAC-SHA256.

    :param password: Plaintext password, as a string.
    :param salt: A 64-bit integer to use as salt.
    :return: The hashed value, as bytes.
    """
    # RSA PBKDF2 (Password-Based Key Derivation Function 2) using HMAC-SHA256
    assert type(salt) is int, repr(type(salt))
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt_to_bytes(salt), 32768)


def hash_pass_legacy(password, salt):
    # Legacy sha1 method: deprecated
    return hashlib.sha1("{0}{1}".format(salt, hashlib.sha1(password).digest())).hexdigest()


def create_hash(password: str) -> Tuple[bytes, int]:
    """
    Create a password hash and matching salt for the first time.

    Returns the generated hash and the salt used to generate it,
    both in hexadecimal form suitable for storing in a database.
    """
    salt = random.getrandbits(64)-(1 << 63)
    pwhash = hash_pass(password, salt)
    return pwhash, salt


class Database(object):
    """
    Provides a high-level, logical interface to the textgame database.

    Requires a database backend class to operate.
    """
    backends = _get_backends()

    def __init__(self, backend, conn_string):
        """
        Instantiates the Database.

        Accepts two parameters. The first parameter is the name of a
        database backend from the textgame.db.backends package. The
        second parameter is an arbitrary string which has meaning to
        the backend class, telling it how to connect to a database.
        """
        # This will raise KeyError if backend doesn't exist
        try:
            backend_cls = self.backends[backend]
        except KeyError as e:
            raise Exception("Requested backend is not available") from e
        if not IDatabaseBackend.implementedBy(backend_cls):
            raise RuntimeError("The named backend class does not implement IDatabaseBackend.")
        # NB: we lie to the type checker about the exact type of _backend to get working completion.
        self._backend: Type[IDatabaseBackend] = backend_cls(conn_string)
        # Double-check that the backend implements the expected interface
        verify.verifyObject(IDatabaseBackend, self._backend)
        self.active = True

    def close(self):
        self._backend.close()
        self.active = False

    @require_connection
    def username_exists(self, username):
        """
        Checks whether an account exists.
        """
        return self._backend.get_user(username) is not None

    @require_connection
    def verify_password(self, username, password):
        """
        Verifies a player login. Returns True if the password is valid for
        the provided username, False otherwise.
        """

        logger.trace(f"Verifying PBKDF2 password hash for user {username}, password {'*'*len(password)} (redacted)")

        # Retrieve user login details
        result = self._backend.get_user(username)
        if result is None:
            logger.trace(f"No such user in database: {username}")
            return False
        pwhash, salt = result
        if pwhash is None:
            logger.debug(f"Hash for {username} is None, no password is set. Setting it to the entered password")
            self._backend.set_password(username, *create_hash(password))
            return True
        logger.trace(f"Successfully retrieved hash={pwhash}, salt={salt} from database")
        # Hash provided password and compare with database
        inputhash = hash_pass(password, salt)
        if pwhash != inputhash:
            logger.debug(f"Password hash mismatch for user {username}")
            return False
        return True

    @require_connection
    def create_account(self, username, password, charname):
        self._backend.set_password(username, *create_hash(password))
        self._backend.create_character(username, charname)

    @require_connection
    def create_character(self, username, charname):
        """
        Given a username and character name, creates the character if it does not exist.

        :param username: The username
        :param charname: The character name
        :return: True if the character was created, False if it exists already.
        """
        logger.trace(f"Creating character {charname!r} for user {username!r}")
        return self._backend.create_character(username, charname) is not None

    @require_connection
    def get_player_id(self, username, charname):
        """
        Given a username and character name, get the Player object id for the character.
        """
        return self._backend.get_player_id(username, charname)

    @require_connection
    def get_user_characters(self, username):
        return self._backend.get_user_characters(username)
        
    @require_connection
    def get_pubkeys(self, username):
        """
        Given a username, retrieves a list of public keys for the user.
        """
        # TODO: #6: Implement public key retrieval
        return []

    @require_connection
    def store_pubkey(self, username, pubkey):
        """
        Given a username and a public key blob, stores that blob in the database.
        The database expects the public key blob to be a raw bytestring; however,
        it will be stored in the database as base64.
        """
        # TODO: #6: Implement public key storage
        pass

    def load_object(self, world, obj):
        """
        Loads an object by ID from the database.

        Takes a world instance and an object ID. The object with the matching id
        will be loaded for the given world.
        """
        result = self._backend.load_object(obj)
        if result is None:
            logger.error(f"The id #{obj} does not exist in the database!")
            return None
        try:
            obtype = DBType(result[0])
        except IndexError as e:
            raise ValueError("Unknown DBType {0} while loading #{1} from the database!".format(result[0], obj))

        logger.debug(f"We loaded {obj}#{result[1]} (type={obtype}) out of the database!")

        # Create Thing instance
        newobj = obtype.type(world, obj, *result[1:])

        #log.debug("Database.load_object(): Returning {0}".format(repr(newobj)))
        return newobj

    @require_connection
    def get_property(self, obj, key):
        """
        Fetches a property value of an object in the database.
        """
        return self._backend.get_property(obj, key)

    @require_connection
    def set_property(self, obj, key, value):
        """
        Sets a property value of an object in the database.

        Currently, this performs an immediate database write.
        """
        self._backend.set_property(obj, key, value)

    def get_contents(self, obj):
        return self._backend.get_contents(obj)

    def create_user(self, username: str, password: str, pubkeys: Sequence[str], character: Optional[str]=None):
        """
        Creates a new user in the database, and also creates an initial character for the user.

        :param username: The username for the new user account.
        :param password: The password for the new user account.
        :param pubkeys: A sequence of public key strings which can be used in future to authenticate this user.
        :param character: A character name for this user's first character. If None, no character will be created.
        """
        self._backend.create_user(username, password, pubkeys)
        if character:
            self._backend.create_character(username, character)

