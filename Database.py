from twisted.cred.checkers import ICredentialsChecker
from twisted.conch.checkers import IAuthorizedKeysDB
from zope.interface import implementer, Interface

from abc import *

import hashlib, struct, random, time, functools

from Things import *
from Util import enum, log, LogLevel

# This is the master list of Thing types as used in the database.
# DO NOT CHANGE THE ORDER OF THIS LIST as it will break existing databases.
thingtypes = [Room, Player, Item, Action, Script]

# Generate enum from the above list
DBType = enum(*[t.__name__ for t in thingtypes])

# Attach dbtype to classes
for t in thingtypes:
    t.dbtype = DBType[t.__name__]

def Thing_of_type(dbtype):
    return thingtypes[dbtype.value()]


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

class DatabaseNotConnected(Exception):
    pass

class IDatabaseBackend(Interface):
    """
    This interface should be implemented by a class which knows how to
    communicate with a particular type of database. For example: SQLite,
    MariaDB, or PostgreSQL.

    Not currently used!
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

    def get_character(self, username, charname):
        """
        Given a username and a character name, this method returns a record from the
        Things table if the character exists, and None otherwise.
        """

    def get_property(self, obj, key):
        """
        This method should return the value of the property named "key" on the object whose
        id is "obj".
        """
        pass

    def set_property(self, obj, key, val):
        """
        This method should set the value of the property named "key" on the object whose
        id is "obj" to the value "val".
        """
        pass


class Database(object):
    # This is an Abstract Base Class
    __metaclass__ = ABCMeta
    
    def __init__(self):
        """
        The Database class is an abstract class, and cannot be instantiated.

        Derived classes must override all abstract methods (the _db_* methods) before they can be instantiated.
        """
        self.active = false

    def create_hash(self, password):
        """
        Create a password hash and matching salt for the first time.

        Returns the generated hash and the salt used to generate it, both in
        hexadecimal form suitable for storing in a database.
        """
        salt = struct.pack('Q', random.getrandbits(64))
        pwhash = self.hash_pass(password, salt).encode('hex_codec')
        return pwhash, salt.encode('hex_codec')

    def hash_pass(self, password, salt):
        """
        Compute a password hash given a plaintext password and a binary salt value.

        This is currently derived using RSA PBKDF2 with 4096 rounds of HMAC-SHA1. This method is
        almost identical to that used by WPA2-PSK wireless networks. Returns a 32-byte hash.

        Returns the raw bytes of the hash as a string. Use str.encode('hex_codec') to get hexadecimal.
        """
        # Legacy sha1 method: deprecated
        #return hashlib.sha1("{0}{1}".format(salt, hashlib.sha1(password).digest())).hexdigest()

        # New method: RSA PBKDF2 (Password-Based Key Derivation Function 2) using HMAC-SHA256
        return hashlib.pbkdf2_hmac("sha1", password, salt, 4096, 32)

    @require_connection
    def user_exists(self, username):
        """
        Checks whether an account exists.
        """
        return self._db_get_user(username) is not None

    @require_connection
    def player_login(self, username, password):
        """
        Verifies a player login. Returns -1 if login failed, or a database ID if successful.
        
        TODO: Incorporate multiple character support. Will return True or False instead of character ID.
        """

        log(LogLevel.Trace, "Verifying salted sha1 password hash for user {0}, password {1} (redacted)".format(username, '*'*len(password)))
        result = self._db_get_user(username)
        if not result:
            log(LogLevel.Trace, "No matching records in database")
            return -1
        pwhash, salt, obj = result
        log(LogLevel.Trace, "Successfully retrieved hash={0}, salt={1}, obj={2} from database".format(pwhash, salt, obj))
        ret = obj if pwhash.decode('hex_codec') == self.hash_pass(password, salt.decode('hex_codec')) else -1
        if ret == -1: 
            log(LogLevel.Debug, "Password hash mismatch for user {0}".format(username))
        return ret

    @require_connection
    def get_player_characters(self, username):
        """
        Retrieves a set of Player object IDs along with the name of that character.
        """
        pass

    @require_connection
    def get_player_id(self, username):
        result = self._db_get_user(username)
        return result[2] if result else None

    @require_connection
    def get_property(self, obj, key):
        """
        Fetches a property value of an object in the database.
        """
        return self._db_get_property(obj, key)

    @require_connection
    def set_property(self, obj, key, value):
        """
        Sets a property value of an object in the database.

        Currently, this performs an immediate database write.
        """
        self._db_set_property(obj, key, value)

    @require_connection
    def close(self):
        """
        Closes the database connection. After calling this method, the instance will become unusable.
        """
        log(LogLevel.Info, "Closing database connection.")
        self._db_close()
        self.active = False

    @require_connection
    def load_object(self, world, obj):
        """
        Loads and returns an object out of the database.
        """

        result = self._db_load_object(obj)
        try:
            obtype = DBType(result[0])
        except IndexError as e:
            raise ValueError("Unknown DBType {0} while loading #{1} from the database!".format(result[0], obj))

        log(LogLevel.Debug, "We loaded {1}#{0} (type={2}) out of the database!".format(result[1], obj, obtype))

        newobj = Thing_of_type(obtype)(world, obj, *result[1:])

        log(LogLevel.Debug, "Database.load_object(): Returning {0}".format(repr(newobj)))
        return newobj

    @require_connection
    def save_object(self, thing):
        """
        Saves a modified object back to the database.
        """
        if not self.active: raise DatabaseNotConnected()
        log(LogLevel.Trace, "Saving {0} to the database...".format(thing))
        assert thing is not None, "Cannot save None!"
        self._db_save_object(thing)

    @require_connection
    def get_contents(self, obj):
        return self._db_get_contents(obj)


    def get_messages(self, obj):
        """
        DEPRECATED.
        """
        raise NotImplementedError("Due to database alterations, this method has been removed.")

        result = self.db_get_messages(obj)
        if result is None: return (None, None, None, None, None)
        return result

    @require_connection
    def new_object(self, objtype, name, parent, owner):
        """
        Initializes a new database object, returning the database ID of the object.

        Required parameters:
        objtype: the type of object to create. This should be a Thing class type.
        owner: The Thing that will own this new object.
        parent: The Thing that will contain this new object.

        This will reuse a deleted object's ID if one is available, thereby permanently
        destroying the deleted object.
        """
        # TODO: Implement creation of new objects in the database
        newid = self._db_get_available_id()
        if newid is None:
            newid = self._db_create_new_object()
        thing = objtype(self.world, newid, name, 0, parent, owner, None, 0, 0, 0, 0)
	return thing
    
    ### Abstract Methods ###
    # The following methods need to be overridden in derived classes.
    # They are also not meant to be called directly, but only called by the Database class itself.

    @abstractmethod
    def _db_create_schema(self, obj):
        """
        Abstract method.

        This method is responsible for ensuring the database is in a state ready for use. It
        is called on every startup, regardless of the state of the database.

        Given an empty database, this method should create any missing tables or other data
        structures, and ensure that they are initialized to a state where the world may start.

        In particular, this method should ensure that Room #0 and Player #1 exist, and should
        correctly initialize them if they do not.

        It is also responsible for checking the database schema version, and running statements
        to upgrade the database if the schema is out of date.
        """
        pass

    @abstractmethod
    def _db_close(self):
        """
        Abstract method.

        This method should ensure that the database has been cleanly written to disk, close the
        underlying database driver, and if neccessary close any files or connections.

        Once this method is called, the class instance should be discarded as it is not expected
        to be reusable. If the database needs to be reopened, a new database instance should be
        created.
        """
        pass

    @abstractmethod
    def _db_load_object(self, obj):
        """
        Abstract method.

        In implementations, returns a tuple of raw data loaded from the database for a given ID.
        Tuple is in the following order:
        (name, type, flags, parent, owner, link, money, created, modified, lastused)
        """
        pass

    @abstractmethod
    def _db_save_object(self, obj):
        """
        Abstract method.
        
        In implementations, causes the given object to be saved back to the database.

        Errata: This method accepts a Thing as input, and should treat it as read-only.
        This needs to be changed so that it instead receives a tuple of data, the same
        way that _db_load_object() returns a tuple of data (and preferably in the same
        order).
        """
        #TODO: Accept a tuple instead of a Thing.
        pass

    @abstractmethod
    def _db_get_property(self, obj, key):
        """
        Abstract method.

        This method should return the value of the property named "key" on the object whose
        id is "obj".
        """
        pass

    @abstractmethod
    def _db_set_property(self, obj, key, val):
        """
        Abstract method.

        This method should set the value of the property named "key" on the object whose
        id is "obj" to the value "val".
        """
        pass

    @abstractmethod
    def _db_get_user(self, username):
        """
        Abstract method.
        
        This method should return the password, salt, and player object ID for the given username.

        NOTE: This may soon change when multiple characters per user is implemented.
        """
        pass

    @abstractmethod
    def _db_get_contents(self, obj):
        """
        Abstract method.

        This method should return a list of database IDs of objects that are contained within
        the object whose id is "obj".

        In database terms, this is usually the result of the following SQL query (or equivalent):
            SELECT id FROM objects WHERE parent==$obj;
        """
        pass

    @abstractmethod
    def _db_get_available_id(self):
        """
        Abstract method.

        This method should fetch the lowest available recycled database ID (i.e. the ID of an
        object that has been deleted such that its ID is available for reuse).

        If there are no such IDs available, then this method should return None, signalling that
        there are no "holes" to be filled in the database, and a fresh ID should be used instead.
        """
        pass

from twisted.internet import defer
from twisted.cred import credentials, error as cred_error

@implementer(ICredentialsChecker)
class CredentialsChecker(object):
    """
    This class implements the ICredentialsChecker interface.

    When provided with credentials which implement IUsernamePassword,
    it will check the credentials against the database and respond
    according to whether the check succeeded.

    This credentials checker is ONLY for checking username and
    password; for SSH public key authentication, a standard
    twisted.conch.checkers.SSHPublicKeyChecker should be used
    in conjunction with our AuthorizedKeystore class.
    """
    # We know how to check a username and password
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, database):
        log(LogLevel.Trace, "CredentialsChecker created")
        self.db = database

    def requestAvatarId(self, credentials):
        log(LogLevel.Trace, "Asked to check credentials for {0}".format(credentials.username))
        try:
            user = credentials.username
            if self.db.player_login(user, credentials.password) == -1:
                log(LogLevel.Info, "{0} failed user authentication".format(user))
                return defer.fail(cred_error.UnauthorizedLogin("Authentication failure: No such user or bad password"))
            else:
                log(LogLevel.Debug, "Successful auth for {0}".format(user))
                return defer.succeed(user)
        except Exception as e:
            from traceback import print_exc
            print_exc(e)

    def _checkPassword(self, creds):
        pass
    def _checkPubkey(self, creds):
        pass

if __name__ == '__main__':
    d = Database()
    
    log(LogLevel.Info, "Test successful password check: " + repr(d.check_pass('admin', 'admin')))
    log(LogLevel.Info, "Test failed password check: " + repr(d.check_pass('admin', 'wrongpass')))

    d.close()

@implementer(IAuthorizedKeysDB)
class AuthorizedKeystore(object):
    """
    This class provides a twisted.conch.checkers.SSHPublicKeyChecker
    with a way to retrieve public keys from our database.
    """
    def __init__(self, database):
        """
        Provides SSH Authorized Keys from the database.
        """
        self.db = database
        
    def getAuthorizedKeys(self, username):
        """
        Fetches the list of public keys (as instances of
        twisted.conch.ssh.keys.Key) that are associated
        with this username.
        """
        #TODO: Implement this
        # The parameter is the value returned by
        # ICredentialsChecker.requestAvatarId().
        log.debug('AuthorizedKeys( "{0}" )'.format(username))
        return []
