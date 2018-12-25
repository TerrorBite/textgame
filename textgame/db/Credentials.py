"""
This file contains credential checkers that verify a user
against the database.
"""

from textgame.Util import log

from twisted.cred.checkers import ICredentialsChecker
from twisted.conch.checkers import IAuthorizedKeysDB
from zope.interface import implementer, Interface
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
        log.trace("CredentialsChecker created")
        self.db = database

    def requestAvatarId(self, credentials):
        log.trace("Asked to check credentials for {0}".format(credentials.username))
        try:
            user = credentials.username
            if self.db.verify_password(user, credentials.password):
                log.info("{0} failed user authentication".format(user))
                return defer.fail(cred_error.UnauthorizedLogin("Authentication failure: No such user or bad password"))
            else:
                log.debug("Successful auth for {0}".format(user))
                return defer.succeed(user)
        except Exception as e:
            from traceback import print_exc
            print_exc(e)

@implementer(IAuthorizedKeysDB)
class AuthorizedKeystore(object):
    """
    This class provides a twisted.conch.checkers.SSHPublicKeyChecker
    with a way to retrieve public keys from our database.
    """
    def __init__(self, database):
        """
        Provides SSH Authorized Keys from the database.

        Expects a textgame.db.Database instance.
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
