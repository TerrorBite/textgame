import time, inspect
from enum import Enum
import logging

def setup_logging(level=logging.INFO):
    """
    Logging is set up, and also extended with new log levels.
    New log levels are annotated below with a plus sign.

     FATAL......The application cannot continue. Also called CRITICAL.
     ERROR......A serious, but recoverable error has occurred.
     WARNING....An unusual condition has occurred that requires attention.
     INFO.......Messages about important, but normal events in the program's life.
    +VERBOSE....Messages about normal events of lesser importance occurring in the program.
     DEBUG......More detailed, frequent messages, only useful while debugging.
    +TRACE......Extremely noisy, may output debug values at almost every step.
    """
    VERBOSE = logging.INFO - 5;
    logging.addLevelName(VERBOSE, 'VERBOSE')
    TRACE = logging.DEBUG - 5;
    logging.addLevelName(TRACE, 'TRACE')

    class Logger(logging.getLoggerClass()):
        def trace(self, msg, *args, **kwargs):
            self.log(TRACE, msg, *args, **kwargs)
        def verbose(self, msg, *args, **kwargs):
            self.log(VERBOSE, msg, *args, **kwargs)

    logging.setLoggerClass(Logger)
    logging.basicConfig(level=level)
    logging.getLogger('Util').verbose("Logging initialised.")

def enum(*args, **named):
    """enum class factory.

    Provides easy enumerated types in Python < 3.4. In Python >= 3.4,
    please consider using the standard enum.Enum class.
    See https://docs.python.org/3/library/enum.html

    An enumeration is defined as follows:
        
        Animals = enum('Cow', 'Pig', 'Sheep', 'Chicken')
        Coins = enum(Penny=1, Nickle=5, Dime=10, Quarter=25)

    The values can used cleanly and directly:
        
    >>> fred = Animals.Sheep
    >>> if fred == Animals.Cow:
    >>>     print 'Mooo!'

    Comparisons work as expected:
    >>> cent = Coins.Penny
    >>> Coins.Penny == cent
    True

    Including inequalities:
    >>> Coins.Quarter < Coins.Nickel
    False
    >>> Coins.Penny < Coins.Dime
    True

    And don't work across types, even if their values are identical.
    >>> Coins.Penny
    Penny=1
    >>> Animals.Pig
    Pig=1
    >>> Coins.Penny == Animals.Pig
    False

    Enum values can also be looked up, by both name and value:
    >>> Coins['Penny']
    Penny=1
    >>> Coins['Dime'].value()
    10
    >>> Coins[25].name()
    'Quarter'

    """

    prenums = zip(args, range(len(args)))+named.items() 
    h = hash(repr(sorted(prenums, key=lambda x: x[1])))

    def factory(n, s, h):
        class EnumValue(enum.EnumValue):
            __slots__ = []
            __name__ = s
            _hash = h
            def __str__(self): return s
            def __repr__(self):
                return "{0}={1}".format(s, n)
            def __int__(self):
                return n
            def __cmp__(self, other):
                if isinstance(other, int): return n.__cmp__(other)
                if hasattr(other, '_hash') and h==other._hash: return n.__cmp__(other.value())
                return NotImplemented
            def __getitem__(self, x):
                return (s, n)[x]
            def __hash__(self): return h+n
            def __eq__(self, other): return other is self or other == n
            @property
            def name(self): return s
            @property
            def value(self): return n
        return EnumValue

    enums = dict(map(lambda x: (x[0], factory(x[1], x[0], h)()), prenums))

    t = type("Enum", (enum.Enum,), enums)
    lookup = dict(map(lambda x: (x[1], x[0]), prenums))
    def Enum(self, s):
        if type(s) is str:
            if s in lookup.values():
                return getattr(t, s)
            else: raise IndexError("No such name in this enumeration")
        elif type(s) is int:
            if s in lookup:
                return getattr(t, lookup[s])
            else: raise IndexError("No such numeric value in this enumeration")
        elif type(s) is enum.EnumValue:
            if s in enums.values():
                return s
            else: raise IndexError("No such value in this enumeration")
        raise TypeError("Expected int or string")
    setattr(t, '__call__', Enum)
    _repr = 'enum({0})'.format(', '.join(repr(x) for x in sorted(enums, key=enums.get)))
    setattr(t, '__repr__', lambda self: _repr )
    setattr(t, '__contains__', lambda self, y: y in lookup or y in lookup.values() or y in enums.values() )
    setattr(t, '__getitem__', Enum)
    def _setattr(self, x, y): raise AttributeError('Enumerations are read-only')
    setattr(t, '__setattr__', _setattr)
    return t()

setattr(enum, "EnumValue", type("enum.EnumValue", (), {}))
setattr(enum, "Enum", type("enum.Enum", (), {}))

"""
This enum defines log levels.

Definitions:

    Fatal: The program has encountered a situation where it cannot possibly continue (incompatible environment, etc) and must exit immediately.

    Error: The program has encountered an error situation which needs to be resolved. It will attempt to continue, or clean up and exit if continuing is not possible.

    Warn: The program has encountered an error which can be automatically recovered from without human intervention, though the cause of the error requires resolution. Program execution will continue.

    Notice: General inportant informational messages regarding changes in program state or other important events that occur during normal program operation. Can also be used for errors where the root cause of the error can be / has been automatically resolved.

    Info: More detailed general informational messages about minor program events and general program flow.

    Debug: Intended for debugging / detailed informational messages. Used to document internal details and the details of frequent, minor program events or flow.

    Trace: Intended for in-depth debugging. Used to log every detail of program operation to track down program errors.
"""
# Note: This is unused with the current logging setup, which uses new log levels.
LogLevel = Enum('LogLevel', ('Trace', 'Debug', 'Info', 'Notice', 'Warn', 'Error', 'Fatal'))

class LogMessage:
    def __init__(self):

def log(level, message):
    frm = inspect.stack()[1]
    mod = inspect.getmodule(frm[0])
    logger = logging.getLogger(mod.__name__)
    # TODO: Format log appropriately
    logger.log(level, LogMessage(message))

def setLogLevel(level):
    "Sets the logging level."
    global _loglevel
    _loglevel = level

import sys
_loglevel = LogLevel.Info
def old_log(level, message):
    if level < _loglevel:
        #print level, loglevel
        return
    log_level_name = level.name.upper() if isinstance(level, LogLevel) else "OTHER"
    if _loglevel <= LogLevel.Debug:
        frm = inspect.stack()[1]
        mod = inspect.getmodule(frm[0])
        sys.stdout.write("{0} [{1}/{3}] {2}\r\n".format(time.strftime('[%H:%M:%S]'),
            log_level_name, message, mod.__name__) )
    else:
        sys.stdout.write("{0} [{1}] {2}\r\n".format(time.strftime('[%H:%M:%S]'),
            log_level_name, message) )

# Handy aliases: log.warn(), log.error(), etc
for level in LogLevel:
    setattr(log, level.name.lower(), log.__get__(level, level.__class__))

def pip_install(*packages):
    try:
        import pip
    except ImportError as e:
        log(LogLevel.Error, "The following packages are required:\r\n    {0}".format(', '.join(packages)))
        return False

    if not hasattr(pip, 'utils'):
        log(LogLevel.Error, "The following packages are required:\r\n    {0}".format(', '.join(packages)))
        return False
        
    if pip.utils.ask("The following packages are required:\r\n    {0}\r\n"\
            "Do you want me to install them locally using pip? (yes/no): "
            .format(', '.join(packages)) , ['yes', 'no']) == 'no': return False

    result = pip.main(['install']+list(packages))
    return result==0

def super_init(*args, **kwargs):
    """
    When called from within a class __init__ function, will call the __init__ of the FIRST parent class only.
    """
    "The frame that called us."
    caller = inspect.currentframe().f_back
    if caller.f_code.co_name == "__init__":
        if caller.f_code.co_argcount < 1: return # bail if caller takes no args (init must take at least one)
        self = caller.f_locals[caller.f_code.co_varnames[0]] # Self is the first argument (regardless of name)
        if not isinstance(caller.f_locals[caller.f_code.co_varnames[0]], object): return # Bail if first arg is not an instance

        # How many levels down the inheritance tree are we?
        stack = [x[0] for x in inspect.stack() if x[3] == "__init__"]
        # Count only frames where the first argument is the "self" object we know
        ctors = [frame for frame in stack if frame.f_code.co_argcount>0 and frame.f_locals[frame.f_code.co_varnames[0]] is self]
        #print repr(ctors)

        cls = self.__class__
        for _ in ctors:
            # Traverse back up the base classes until we reach the right level
            cls = cls.__bases__[0]
        cls.__init__(self, *args, **kwargs)
        import code
        code.interact(local=locals())
