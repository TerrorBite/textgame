from twisted.cred.checkers import ICredentialsChecker
from zope.interface import implements

import hashlib, struct, random, time

from Things import *
from Util import enum, log, LogLevel

DBType = enum('Room', 'Player', 'Item', 'Action', 'Script')

typemap = {
        DBType.Room: Room,
        DBType.Player: Player,
        DBType.Item: Item,
        DBType.Action: Action,
        DBType.Script: Script
        }

active = True

class DatabaseNotConnected(Exception):
    pass

class Database(object):

    def create_hash(self, password):
        """Create a password hash and matching salt for the first time."""
        salt = struct.pack('Q', random.getrandbits(64))
        pwhash = self.hash_pass(password, salt)
        return pwhash, salt.encode('hex_codec')

    def hash_pass(self, password, salt):
        """Compute a password hash given a plaintext password and a binary salt value."""
        return hashlib.sha1("{0}{1}".format(salt, hashlib.sha1(password).digest())).hexdigest()

    def player_login(self, username, password):
        """
        Verifies a player login. Returns -1 if login failed, or a database ID if successful.
        Password may be None to locate a player by username without verifying 
        """
        if not active: raise DatabaseNotConnected()

        log(LogLevel.Trace, "Verifying salted sha1 password hash for user {0}, password {1} (redacted)".format(username, '*'*len(password)))
        result = self.db_get_user(username)
        if not result:
            log(LogLevel.Trace, "No matching records in database")
            return -1
        pwhash, salt, obj = result
        log(LogLevel.Trace, "Successfully retrieved hash={0}, salt={1}, obj={2} from database".format(pwhash, salt, obj))
        ret = obj if pwhash == self.hash_pass(password, salt.decode('hex_codec')) else -1
        if ret == -1: 
            log(LogLevel.Debug, "Password hash mismatch for user {0}".format(username))
        return ret

    def get_player_id(self, username):
        result = self.db_get_user(username)
        return result[2] if result else None

    def get_property(self, obj, key):
        return self.db_get_property(obj, key)

    def set_property(self, obj, key, value):
        self.db_set_property(obj, key, value)

    def __init__(self):
        raise NotImplementedError("Can't initialize Database class: Need a specific database implementation")

    def close(self):
        log(LogLevel.Info, "Closing database connection.")
        self.db_close()
        self.active = False

    def load_object(self, world, obj):
        """Loads and returns an object out of the database."""
        if not active: raise DatabaseNotConnected()

        result = self.db_load_object(obj)
        obtype = DBType(result[1])
        log(LogLevel.Debug, "We loaded {1}#{0} (type={2}) out of the database!".format(result[0], obj, obtype))

        if obtype in typemap:
            newobj = typemap[obtype](world, obj, *result)
        else:
            raise ValueError("Unknown DBType {0} while loading #{1} from the database!".format(result[1], obj))

        log(LogLevel.Debug, "Database.load_object(): Returning {0}".format(repr(newobj)))
        return newobj

    def db_load_object(self, obj):
        """
        In implementations, returns a tuple of raw data loaded from the database for a given ID.
        Tuple is in the following order:
        (name, type, flags, parent, owner, link, money, created, modified, lastused)
        """
        raise NotImplementedError("Abstract method")

    def save_object(self, thing):
        """Saves a modified object back to the database."""
        if not active: raise DatabaseNotConnected()
        log(LogLevel.Trace, "Saving {0} to the database...".format(thing))
        assert thing is not None, "Cannot save None!"
        self.db_save_object(thing)

    def get_contents(self, obj):
        if not active: raise DatabaseNotConnected()

        return self.db_get_contents(obj)


    def get_messages(self, obj):
        if not active: raise DatabaseNotConnected()

        result = self.db_get_messages(obj)
        if result is None: return (None, None, None, None, None)
        return result

    def get_new_id(self):

        pass


from twisted.internet import defer
from twisted.cred import credentials, error as cred_error
class CredentialsChecker(object):
    implements(ICredentialsChecker)
    credentialInterfaces = (credentials.IUsernamePassword,)

    def __init__(self, database):
        self.db = database

    def requestAvatarId(self, credentials):
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

if __name__ == '__main__':
    d = Database()
    
    log(LogLevel.Info, "Test successful password check: " + repr(d.check_pass('admin', 'admin')))
    log(LogLevel.Info, "Test failed password check: " + repr(d.check_pass('admin', 'wrongpass')))

    d.close()
