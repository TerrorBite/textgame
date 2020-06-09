import typing
from twisted.cred.credentials import ICredentials
from zope.interface import Interface, Attribute


class IUserProtocol(Interface):
    #TODO: Document this interface.
    def write_line(line):
        """
        Sends a complete line of text to the user.
        """
        pass  # Interface method

    def resize(width, height):
        """
        Notify a terminal-based protocol of a change in window size.
        """
        pass  # Interface method


# noinspection PyMethodParameters
class IUsernameRequest(ICredentials):
    """
    I am a request for an available username.
    """

    username = Attribute("The desired username for the new account.")

    def create_account(database):
        """
        Creates the account.

        :param database: Some form of database in which this account should be created.
            The database should implement IDatabaseBackend.
        :return: True if successful, False if not successful, or a Deferred which will
            resolve to one of these values.
        """

