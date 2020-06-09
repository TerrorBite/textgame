
import zope.interface
from textgame.db import IDatabaseBackend
from textgame.db.backends import Sqlite


class TestSqlite:
    """
    Tests the Sqlite backend class.
    """

    def test_interface(self):
        assert IDatabaseBackend.implementedBy(Sqlite.Sqlite)
