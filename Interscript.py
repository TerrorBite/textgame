"""
Interscript is a lisp-like substitution language.
"""

import re
from functools import wraps

re_interscript = re.compile(ur'{(\[.*?[^\\]\])}')

re_special = re.compile(ur'[][<]')
re_unescape = re.compile(ur'\\([][<>{}\\])')
re_funcname = re.compile(ur'\[(\w+)([]:])')

funchandlers = {}
class funcHandler:
    """
    Decorator that marks a method as a command handler.
    """
    def __init__(self, *aliases):
        self.funcs = aliases
    def __call__(self, f):
        for func in self.funcs:
            funchandlers[func] = f

class ResolvableText(object):
    """
    Class that represents a string of text which may contain callables which need to be resolved to text.
    """
    def __init__(self):
        self.parts = []
        self.resolved = None
    def __iadd__(self, other):
        """
        Appends an item to the end of this ResolvableText.

        The item is expected to be one of three types:

        - A string-like object
        - Another ResolvableText
        - A callable that takes no parameters and returns a string-like object

        In the case that the item is another ResolvableText, its individual parts will be appended.
        """
        # Don't bother for falsy objects (zero length strings, etc)
        if not other: return self

        if isinstance(other, ResolvableText):
            self.parts += other.parts
        else:
            self.parts.append(other)
        return self

    def __repr__(self):
        return "<ResolvableText{0}>".format(self.parts)

    def resolve(self):
        """
        Resolves this ResolvableText to a string, returning the string.
        Any callables embedded within the ResolvableText will be called, and the return value substituted into the string.
        """
        if self.resolved is None:
            self.resolved = u''.join([x() if callable(x) else x for x in self.parts])
        return self.resolved

    def split(self, sep):
        """
        Splits the ResolvableText into one or more ResolvableTexts using a separator.

        This will only affect text portions of the ResolvableText. Function components will never be split.
        """
        parts = list(self.parts) # Take copy because we are going to pop from it
        current_out = ResolvableText()
        out = []
        
        while len(parts) > 0:
            part = parts.pop(0) # Pop part to examine
            if callable(part):
                # Don't try and split callables
                current_out += part
                continue 
            splits = part.split(sep) # Look for (and split on) separators
            while len(splits) > 1:
                # Comma detected, add bit before it
                current_out += splits.pop(0)
                out.append(current_out) # Finalize current_out
                current_out = ResolvableText()
                # if multiple commas, loop will run again
            current_out += splits[0]
        out.append(current_out) # Finalize current_out

        # Return list of ResolvableTexts
        return out            


def wrap_func(func, params):
    """
    Wraps a function, taking a sequence of parameters. Returns the wrapper.
    The wrapper, when called, will resolve any ResolvableText parameters to strings, then call the original function with the resulting parameter list.
    The wrapper does not take any parameters itself. It returns what the wrapped function returns.
    """
    depth = params[0].depth if isinstance(params[0], Parser) else 0
    #strparams = [p.resolve() if isinstance(p, ResolvableText) else p for p in params]
    #print "{2}Wrapping: {0} with params {1}".format(func.__name__, repr(params), depth*' ')
    @wraps(func)
    def wrapper():
        return func(*[p.resolve() if isinstance(p, ResolvableText) else p for p in params])
    return wrapper


class Parser(object):

    def depth_meter(func):
        """debug function"""
        @wraps(func)
        def wrapper(self, *params):
            self.depth += 1
            ret = func(self, *params)
            self.depth -= 1
            return ret
        return wrapper
    
    def __init__(self, player):
        """
        Creates an Interscript parser for a player.
        """
        self.player = player
        self.depth = 0

    def parse_prop(self, thing, propname, action, arg):
        """
        Parses a property of a Thing in the context of this player.
        """
        self.thing = thing
        self.propname = propname
        self.action = action
        self.arg = arg

        self.parse(thing[propname])

    def parse(self, string):
        """
        Parses an arbitrary string for Interscript.
        """

        def repl(match):
            """
            This func executes upon an Interscript block within a string.
            """
            #print 'Parsing string'
            # Parse into a ResolvableText
            result, resultlen = self._parse_text(match.group(1))
            # Resolve the text and return the string
            #print 'Resolving parsed string'
            return result.resolve()

        return re_interscript.sub(repl, string)

    @depth_meter
    def _parse_func(self, source):
        """
        Parses a function.
        Returns (callable, length_consumed).
        """
        assert source[0] == '['

        m = re_funcname.match(source)
        funcname = m.group(1)
        consumed = m.end()

        if funcname not in funchandlers:
            raise Exception("Unknown function")

        params = []
        if m.group(2) == ':':
            # If the function name is terminated by a : then it has parameters
            params, paramslen = self._parse_text(source[consumed:])
            params = params.split(',') # Split ResolvableText into several by commas
            consumed += paramslen
        # we're now at the end of the function

        func = funchandlers[funcname]
        func = wrap_func(func, [self]+params)
        return func, consumed

    def _parse_text(self, source):
        """
        Parses text, looking for functions.
        Returns (ResolvableText, length_consumed).
        """
        text = ResolvableText()
        consumed = 0

        while True:
            # Find first [, <, or ]
            m = re_special.search(source)
            if m is None:
                # If we found nothing then we are at the end of the source
                consumed += len(source)
                return text, consumed

            char = m.group(0) # what did we find?
            partlen = m.start() # and where?

            # Store and consume text up to this point
            text += source[:partlen]
            source = source[partlen:]
            consumed += partlen
            
            if char == ']':
                # We found the end of a function. This means we need to bail out
                return text, consumed + 1 # Add one to consume the closing ]
            elif char == '[':
                # We found a function! Parse it
                part, partlen = self._parse_func(source)
            elif char == '<':
                # We found a variable! Parse it
                part, partlen = self._parse_var(source)
            # Consume text that we just parsed
            text += part
            source = source[partlen:]
            consumed += partlen
        
    def _parse_var(self, text):
        """
        Like _parse(), but handles variables.
        """
        # Find the end of the variable name
        s = text.find('>')
        var = text[1:s]

        # TODO: Replace with actual value
        result = "(Value of {0})".format(var)

        return result, s+1

    def _execute(self, func):
        #TODO: Remove this
        if ':' in func:
            fname, params = func.split(':',1)
            #TODO: param value escaping?
            params = params.split(',')
        else: fname = func
        return func

    @funcHandler('null')
    def func_null(self, *params):
        return ''

    @funcHandler('name')
    def func_name(self, dbref):
        if dbref.startswith('#'):
            dbref = int(dbref[1:])

        #TODO: Implement this
        return "[NAMEOF#{0}]".format(dbref)

    @funcHandler('cat')
    def func_cat(self, *params):
        # Largely a test function. Useless in practice.
        return ''.join(params)

        
if __name__ == '__main__':
    # Run some tests
    p = Parser(None)
    test_strings = [
            "This is a test string.",
            "{[null]}",
            "This string contains {[cat:some, ,Interscript]}.",
            "This is {[cat:nested,[name:#925][null:This text is invisible] ,Interscript]}!",
            ]
    #test_strings.append(' '.join(test_strings))

    for test in test_strings:
        print "INPUT : " + repr(test)
        print "OUTPUT: " + repr(p.parse(test))
