# pyflyby/_flags.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __future__
import ast
import operator
import six
from   six.moves                import reduce

from   pyflyby._util            import cached_attribute


# Initialize mappings from compiler_flag to feature name and vice versa.
_FLAG2NAME = {}
_NAME2FLAG = {}
for name in __future__.all_feature_names:
    flag = getattr(__future__, name).compiler_flag
    _FLAG2NAME[flag] = name
    _NAME2FLAG[name] = flag
for name in dir(ast):
    if name.startswith('PyCF'):
        flag_name = name[len('PyCF_'):].lower()
        flag = getattr(ast, name)
        _FLAG2NAME[flag] = flag_name
        _NAME2FLAG[flag_name] = flag
_FLAGNAME_ITEMS = sorted(_FLAG2NAME.items())
_ALL_FLAGS = reduce(operator.or_, _FLAG2NAME.keys())


class CompilerFlags(int):
    """
    Representation of Python "compiler flags", i.e. features from __future__.

      >>> print(CompilerFlags(0x18000).__interactive_display__())
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> print(CompilerFlags(0x10000, 0x8000).__interactive_display__())
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> print(CompilerFlags('with_statement', 'print_function').__interactive_display__())
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

    This can be used as an argument to the built-in compile() function. For
    instance, in Python 2::

      >>> compile("print('x', file=None)", "?", "exec", flags=0, dont_inherit=1) #doctest:+SKIP
      Traceback (most recent call last):

        ...
      SyntaxError: invalid syntax

      >>> compile("print('x', file=None)", "?", "exec", flags=CompilerFlags("print_function"), dont_inherit=1) #doctest:+ELLIPSIS
      <code object ...>

    """

    def __new__(cls, *args):
        """
        Construct a new ``CompilerFlags`` instance.

        :param args:
          Any number (zero or more) ``CompilerFlags`` s, ``int`` s, or ``str`` s,
          which are bitwise-ORed together.
        :rtype:
          `CompilerFlags`
        """
        if len(args) == 0:
            return cls._ZERO
        elif len(args) == 1:
            arg, = args
            if isinstance(arg, cls):
                return arg
            elif arg is None:
                return cls._ZERO
            elif isinstance(arg, int):
                return cls.from_int(arg)
            elif isinstance(arg, six.string_types):
                return cls.from_str(arg)
            elif isinstance(arg, ast.AST):
                return cls.from_ast(arg)
            elif isinstance(arg, (tuple, list)):
                return cls(*arg)
            else:
                raise TypeError("CompilerFlags: unknown type %s"
                                % (type(arg).__name__,))
        else:
            flags = [int(cls(x)) for x in args]
            return cls.from_int(reduce(operator.or_, flags))

    @classmethod
    def from_int(cls, arg):
        if arg == 0:
            return cls._ZERO # Instance optimization
        self = int.__new__(cls, arg)
        bad_flags = int(self) & ~_ALL_FLAGS
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

    @classmethod
    def from_ast(cls, nodes):
        """
        Parse the compiler flags from AST node(s).

        :type nodes:
          ``ast.AST`` or sequence thereof
        :rtype:
          ``CompilerFlags``
        """
        if isinstance(nodes, ast.Module):
            nodes = nodes.body
        elif isinstance(nodes, ast.AST):
            nodes = [nodes]
        flags = []
        for node in nodes:
            if not isinstance(node, ast.ImportFrom):
                # Got a non-import; stop looking further.
                break
            if not node.module == "__future__":
                # Got a non-__future__-import; stop looking further.
                break
            # Get the feature names.
            names = [n.name for n in node.names]
            flags.extend(names)
        return cls(flags)

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
        if self == 0:
            return o
        return CompilerFlags(int(self) | int(o))

    def __ror__(self, o):
        return self | o

    def __and__(self, o):
        o = CompilerFlags(o)
        return CompilerFlags(int(self) & int(o))

    def __rand__(self, o):
        return self & o

    def __xor__(self, o):
        o = CompilerFlags(o)
        return CompilerFlags(int(self) ^ int(o))

    def __rxor__(self, o):
        return self ^ o

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
