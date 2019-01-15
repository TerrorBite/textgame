"""
Internal module of textgame.db

This file provides the Database class and the DBType enum.
"""

__all__ = ["Database", "DBType"]

# System imports
import hashlib, struct, random, time, functools

# Local imports
from textgame.db import backends, IDatabaseBackend
from textgame.Things import *
from textgame.Util import enum, log, LogLevel

# 1. This is the master list of Thing types as used in the database.
# DO NOT CHANGE THE ORDER OF THIS LIST as it will break existing databases.
thingtypes = [Room, Player, Item, Action, Script]

# 2. Generate enum from the above list
DBType = enum(*[t.__name__ for t in thingtypes])

# 3. Attach dbtype to classes
for t in thingtypes:
    t.dbtype = DBType[t.__name__]

def Thing_of_type(dbtype):
    """
    Given a DBType, returns the Thing class for that type.
    """
    return thingtypes[dbtype.value()]

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


def hash_pass(password, salt):
    """
    Compute a password hash given a plaintext password and a binary salt value.

    This is currently derived using RSA PBKDF2 with 4096 rounds of
    HMAC-SHA1. This method is almost identical to that used by
    WPA2-PSK wireless networks. Returns a 32-byte hash.

    Returns the raw bytes of the hash as a string. Use
    str.encode('hex_codec') to get hexadecimal.
    """
    # RSA PBKDF2 (Password-Based Key Derivation Function 2)
    # using HMAC-SHA256
    return hashlib.pbkdf2_hmac("sha1", password, salt, 4096, 32)

def hash_pass_legacy(password, salt):
    # Legacy sha1 method: deprecated
    return hashlib.sha1("{0}{1}".format(salt, hashlib.sha1(password).digest())).hexdigest()

def create_hash(password):
    """
    Create a password hash and matching salt for the first time.

    Returns the generated hash and the salt used to generate it,
    both in hexadecimal form suitable for storing in a database.
    """
    salt = struct.pack('Q', random.getrandbits(64))
    pwhash = hash_pass(password, salt).encode('hex_codec')
    return pwhash, salt.encode('hex_codec')


class Database(object):
    """
    Provides a high-level, logical interface to the textgame database.

    Requires a database backend class to operate.
    """
    def __init__(self, backend, conn_string):
        """
        Instantiates the Database.

        Accepts two parameters. The first parameter is the name of a
        database backend from the textgame.db.backends package. The
        second parameter is an arbitrary string which has meaning to
        the backend class, telling it how to connect to a database.
        """
        # This will raise AttributeError if backend doesn't exist
        backend_cls = getattr(backends, backend)
        if not IDatabaseBackend.implementedBy(backend_cls):
            raise RuntimeError("The named backend class does not implement IDatabaseBackend.")
        self._backend = backend_cls(conn_string)
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

        log.trace("Verifying PBKDF2 password hash for user {0}, password {1} (redacted)".format(username, '*'*len(password)))

        # Retrieve user login details
        result = self._backend.get_user(username)
        if result is None:
            log.trace("No such user in database: {0}".format(username))
            return False
        pwhash, salt = result
        log.trace("Successfully retrieved hash={0}, salt={1} from database".format(pwhash, salt))
        # Hash provided password and compare with database
        inputhash = hash_pass(password, salt.decode('hex_codec'))
        log.trace("Hashed input password to: {0}".format(inputhash.encode('hex_codec')))
        if pwhash.decode('hex_codec') != inputhash:
            log.debug("Password hash mismatch for user {0}".format(username))
            return False
        return True

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
        #TODO: Implement public key retrieval
        return []

    @require_connection
    def store_pubkey(self, username, pubkey):
        """
        Given a username and a public key blob, stores that blob in the database.
        The database expects the public key blob to be a raw bytestring; however,
        it will be stored in the database as base64.
        """
        #TODO: Implement public key storage
        pass

    def load_object(self, world, obj):
        """
        Loads an object by ID from the database.

        Takes a world instance and an object ID. The object with the matching id
        will be loaded for the given world.
        """
        result = self._backend.load_object(obj)
        if result is None:
            log.error("The id #{0} does not exist in the database!".format(obj))
            return None
        try:
            obtype = DBType(result[0])
        except IndexError as e:
            raise ValueError("Unknown DBType {0} while loading #{1} from the database!".format(result[0], obj))

        log.debug( "We loaded {1}#{0} (type={2}) out of the database!".format(result[1], obj, obtype))

        # Create Thing instance
        newobj = Thing_of_type(obtype)(world, obj, *result[1:])

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
