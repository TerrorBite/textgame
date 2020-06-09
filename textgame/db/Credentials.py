"""
This file contains credential checkers that verify a user
against the database.
"""

from textgame.Util import get_logger

from twisted.cred.checkers import ICredentialsChecker
from twisted.conch.checkers import IAuthorizedKeysDB
from zope.interface import implementer, Interface
from twisted.internet import defer
from twisted.cred import credentials, error as cred_error

from textgame.World import World
from textgame.interfaces import IUsernameRequest

logger = get_logger(__name__)


# CHANGE OF PLANS.

# Rather than use a standard credentials cha


@implementer(ICredentialsChecker)
class DBCredentialsChecker(object):
    """
    This class implements the ICredentialsChecker interface.

    This class accepts a World instance and will check credentials against the underlying database used by that World.
    It can handle instances which conform to the following interfaces:

    * credentials.IUsernamePassword: Will check if the password for that user is correct.
    * textgame.interfaces.IUsernameRequest: Will check if a username is available.

    For SSH public key authentication, a standard twisted.conch.checkers.SSHPublicKeyChecker should be used
    in conjunction with our AuthorizedKeystore class.
    """
    credentialInterfaces = (

        # We know how to check a username and password.
        credentials.IUsernamePassword,

        # We know how to create new user accounts.
        IUsernameRequest
    )

    def __init__(self, world: World):
        logger.trace("CredentialsChecker created")
        self.db = world.db
        self.world = world

    def requestAvatarId(self, creds):

        if IUsernameRequest.providedBy(creds):
            logger.trace("Asked to check if {0} is available".format(creds.username))
            if self.db.username_exists(creds.username):
                return defer.succeed(creds.username)
            else:
                return defer.fail(cred_error.LoginFailed("Username does not exist"))

        else:
            logger.trace("Asked to check credentials for {0}".format(creds.username))
            try:
                user = creds.username
                if not self.db.verify_password(user, creds.password):
                    logger.info("{0} failed user authentication".format(user))
                    return defer.fail(
                        cred_error.UnauthorizedLogin("Authentication failure: No such user or bad password")
                    )
                else:
                    logger.debug("Successful auth for {0}".format(user))
                    return defer.succeed(user)
            except Exception:
                logger.exception("Unable to check credentials")


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
        logger.debug('AuthorizedKeys( "{0}" )'.format(username))
        return []
