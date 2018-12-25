"""
This module provides the Database class, which provides a database for
the textgame World. Multiple backends can be supported. See the module
textgame.db.backends for supported backends.
"""
from ._interface import IDatabaseBackend
from ._database import Database, DBType

__all__ = ["IDatabaseBackend", "Database", "DBType"]
