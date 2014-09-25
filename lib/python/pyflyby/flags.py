
from __future__ import absolute_import, division, with_statement

import __future__
import operator

from   pyflyby.util             import cached_attribute


# Initialize mappings from compiler_flag to name and vice versa.
_FLAG2NAME = {}
_NAME2FLAG = {}
for name in __future__.all_feature_names:
    flag = getattr(__future__, name).compiler_flag
    _FLAG2NAME[flag] = name
    _NAME2FLAG[name] = flag
_FLAGNAME_ITEMS = sorted(_FLAG2NAME.items())
_ALL_FLAGS = reduce(operator.or_, _FLAG2NAME.keys())


class CompilerFlags(int):
    """
    Python "compiler flags", i.e. features from __future__.

      >>> CompilerFlags(0x18000)
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> CompilerFlags(0x10000, 0x8000)
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> CompilerFlags('with_statement', 'print_function')
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

    This can be used as an argument to the built-in compile() function:

      >>> compile("print('x', file=None)", "?", "exec", flags=0, dont_inherit=1)
      SyntaxError: invalid syntax

      >>> compile("print('x', file=None)", "?", "exec", flags=CompilerFlags("print_function"), dont_inherit=1)
      SyntaxError: invalid syntax

    """

    def __new__(cls, *args):
        """
        Construct a new C{CompilerFlags} instance.

        @param args:
          Any number (zero or more) C{CompilerFlags}s, C{int}s, or C{str}s,
          which are bitwise-ORed together.
        @rtype:
          L{CompilerFlags}
        """
        if len(args) == 0:
            return cls._ZERO
        elif len(args) == 1:
            arg, = args
            if isinstance(arg, cls):
                return arg
            elif isinstance(arg, int):
                return cls.from_int(arg)
            elif isinstance(arg, basestring):
                return cls.from_str(arg)
            elif isinstance(arg, (tuple, list)):
                return cls(*arg)
            else:
                raise TypeError("CompilerFlags: unknown type %s"
                                % (type(arg).__name__,))
        else:
            flags = [cls(x) for x in args]
            return cls.from_int(reduce(operator.or_, flags))

    @classmethod
    def from_int(cls, arg):
        if arg == 0:
            return cls._ZERO # Instance optimization
        self = int.__new__(cls, arg)
        bad_flags = self & ~_ALL_FLAGS
        if bad_flags:
            raise ValueError(
                "CompilerFlags: unknown flag value(s) %s" % (bin(bad_flags),))
        return self

    @classmethod
    def from_str(cls, arg):
        try:
            flag = _NAME2FLAG[arg]
        except KeyError:
            raise ValueError(
                "CompilerFlags: unknown flag %r" % (arg,))
        return cls.from_int(flag)

    @cached_attribute
    def names(self):
        return tuple(
            n
            for f, n in _FLAGNAME_ITEMS
            if f & self)

    def __or__(self, o):
        if o == 0:
            return self
        o = CompilerFlags(o)
        return CompilerFlags(int(self) | int(o))

    def __ror__(self, o):
        return self | o

    def __repr__(self):
        return "CompilerFlags(%s)" % (hex(self),)

    def __str__(self):
        return hex(self)

    def __interactive_display__(self):
        s = repr(self)
        if self != 0:
            s += " # from __future__ import " + ", ".join(self.names)
        return s


CompilerFlags._ZERO = int.__new__(CompilerFlags, 0)
