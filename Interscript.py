"""
Interscript is a lisp-like substitution language.
"""

import re

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
    def add(self, part):
        self.parts.append(part)
    def resolve(self):
        return ''.join([x() if callable(x) else x for x in self.parts])

def wrap_func(func, params):
    """
    Wraps a function, taking a sequence of parameters. Returns the wrapper.
    When called, the wrapper will call the original function with those parameters.
    The wrapper does not take any parameters itself. It returns what the wrapped function returns.
    """
    def wrapper():
        func(*params)
    return wrapper


class Parser(object):
    
    def __init__(self, player):
        """
        Creates an Interscript parser for a player.
        """
        self.player = player

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
            result, more = self._parse(match.group(1))
            while more:
                pos = more.find('[')
                result += more[:pos]
                val, more = self._parse(more[pos:])
                result += val
            return result

        return re_interscript.sub( repl, thing[propname])

    def _parse(self, text):
        """
        Searches the provided string from the second character onwards for the first instance of either a [ or a ]. It assumes that the first character is a [ and is searching for the corresponding ] character.
        Upon finding a [, it calls itself on the string from that character onwards. When that returns, it replaces the search string from that point on with the returned values, and then resumes parsing from the replacement onwards.
        Upon finding a ], it stops searching, then parses and executes the function that was contained in the brackets. It then returns a tuple consisting of two parts:
        The first part contains the replacement value for the string up to and including the ]. The second part contains any unparsed text that still remains beyond that position.
        
        """

        char = ''

        pos = 1
        while True:
            m = re_special.search(text[pos:])
            char = m.group(0)

            s = pos+m.start()
            if char == '[':
                repl, more = self._parse( text[s:] )
                text = text[:s] + repl + more
                pos = s+len(repl)
                continue
            if char == '<':
                # like [, but vars
                repl, more = self._parse_var( text[s:] )
                text = text[:s] + repl + more
                pos = s+len(repl)
                continue
            if char == ']':
                # we have hit the end of the function. Now we execute it
                func = text[1:s]
                print "Executing func: ", func
                
                result = _execute(func)

                return result, text[s+1:]
                
    def _parse_func(self, source):
        """
        Parses a function.
        Returns (callable, length_consumed).
        """
        assert source[0] == '['

        m = re_funcname.match(source)
        funcname = m.group(1)
        consumed = m.end()

        params = []
        if m.group(2) == ':':
            # account for closing ]
            params, l = _parse_params(source[consumed:])
            l += 1
            

        if funcname not in funchandlers:
            raise Exception("Unknown function")

        func = funchandlers[funcname]
        func = wrap_func(func, params)
        return func, consumed

    def _parse_params(self, source):
        """
        Parses function parameters.
        Returns (ResolvableText, length_consumed).
        """

        return text.split(','), consumed
        pass
        
    def _parse_var(self, text):
        """
        Like _parse(), but handles variables.
        """
        s = text.find('>')
        var = text[1:s]

        # TODO: Replace with actual value
        result = "(Value of {0})".format(var)

        return result, text[s+1:]

    def _execute(self, func):
        #TODO: Func
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

        
