"""
Interscript is a lisp-like substitution language.
"""

import re

re_interscript = re.compile(ur'{(\[.*?[^\\]\])}')

re_special = re.compile(ur'[][<]')
re_unescape = re.compile(ur'\\([][<>{}\\])')

class Parser(object):
    
    def __init__(self, player):
        """
        Creates an Interscript parser for a player.
        """
        self.player = player

    def parse(self, thing, propname, action, arg):
        """
        Parses a property of a thing.
        """
        self.thing = thing
        self.propname = propname
        self.action = action
        self.arg = arg

        return re_interscript.sub( lambda match: self._parse(match.group(1))[0], thing[propname])

    def _parse(self, text):
        """
        Searches the provided string for the first instance of either a [ or a ].
        Upon finding a [, it splits the string just before it and calls parse() on the second half.
        Upon finding a ], it processes the contents, then returns.

        The return value is a tuple:
            0: The replacement string and remaining unparsed text.
            1: The position in the original string where parsing should be resumed.
        """

        char = ''

        pos = 1
        while True:
            m = re_special.search(text[pos:])
            char = m.group(0)

            s = pos+m.start()
            if char == '[':
                repl, ln = self._parse( text[s:] )
                text = text[:s] + repl
                pos = s+ln
                continue
            if char == '<':
                # like [, but vars
                repl, ln = self._parse_var( text[s:] )
                text = text[:s] + repl
                pos = s+ln
                continue
            if char == ']':
                # we have hit the end of the function. Now we execute it
                func = text[1:s]
                print "Executing func: ", func

                return "(Result of {0}){1}".format(func, text[s+1:]), s+1
                
    def _parse_var(self, text):
        """
        Like _parse, but handles variables.
        """
        s = text.find('>')
        var = text[1:s]
        remain = text[s+1:]

        return "(Value of {0}){1}".format(var, remain), s+1

            
            
        

        
