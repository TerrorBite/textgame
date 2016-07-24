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
                result = "(Result of {0})".format(func) #TODO: Actually call func

                return result, text[s+1:]
                
    def _parse_var(self, text):
        """
        Like _parse(), but handles variables.
        """
        s = text.find('>')
        var = text[1:s]

        # TODO: Replace with actual value
        result = "(Value of {0})".format(var)

        return result, text[s+1:]

            
            
        

        
