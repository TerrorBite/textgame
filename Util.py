import time, inspect

def enum(*args, **named):
    """enum class factory.

    Provides easy enumerated types in Python. An enumeration is defined as follows:
        
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
        class EnumValue:
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
            def __eq__(self, other): return other is self or n.__eq__(other)
            def name(self): return s
            def value(self): return n
        return EnumValue

    enums = dict(map(lambda x: (x[0], factory(x[1], x[0], h)()), prenums))

    t = type('Enum', (), enums)
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
        raise TypeError("Expected int or string")
    setattr(t, '__call__', Enum)
    _repr = 'enum({0})'.format(', '.join(repr(x) for x in sorted(enums, key=enums.get)))
    setattr(t, '__repr__', lambda self: _repr )
    setattr(t, '__getitem__', Enum)
    def _setattr(self, x, y): raise AttributeError('Enumerations are read-only')
    setattr(t, '__setattr__', _setattr)
    return t()

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
LogLevel = enum('Trace', 'Debug', 'Info', 'Notice', 'Warn', 'Error', 'Fatal')

loglevel = LogLevel.Info

def setLogLevel(level):
    "Sets the logging level."
    global loglevel
    loglevel = level

import sys
def log(level, message):
    if level < loglevel:
        #print level, loglevel
        return
    if loglevel <= LogLevel.Debug:
        frm = inspect.stack()[1]
        mod = inspect.getmodule(frm[0])
        sys.stdout.write("{0} [{1}/{3}] {2}\r\n".format(time.strftime('[%H:%M:%S]'), level.name().upper(), message, mod.__name__) )
    else: sys.stdout.write("{0} [{1}] {2}\r\n".format(time.strftime('[%H:%M:%S]'), level.name().upper(), message) )
