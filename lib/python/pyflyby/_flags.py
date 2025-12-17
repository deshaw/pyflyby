# pyflyby/_flags.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



import __future__
import ast
from   functools                import reduce
import operator
import warnings

from   pyflyby._util            import cached_attribute
from   typing                   import Tuple

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

      >>> print(CompilerFlags(0x18000).__interactive_display__()) # doctest: +SKIP
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> print(CompilerFlags(0x10000, 0x8000).__interactive_display__()) # doctest: +SKIP
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> print(CompilerFlags('with_statement', 'print_function').__interactive_display__()) # doctest: +SKIP
      CompilerFlags(0x18000) # from __future__ import with_statement, print_function

      >>> compile("print('x', file=None)", "?", "exec", flags=CompilerFlags("print_function"), dont_inherit=1) #doctest:+ELLIPSIS
      <code object ...>

    """

    # technically both those are compiler flags, but we can't use Self. May need typing_extensions ?
    _ZERO:int
    _UNKNOWN: int

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
                warnings.warn('creating CompilerFlags from integers is deprecated, '
                ' flags values change between Python versions. If you are sure use .from_int',
                DeprecationWarning, stacklevel=2)
                return cls.from_int(arg)
            elif isinstance(arg, str):
                return cls.from_str(arg)
            elif isinstance(arg, ast.AST):
                return cls.from_ast(arg)
            elif isinstance(arg, (tuple, list)):
                return cls(*arg)
            else:
                raise TypeError("CompilerFlags: unknown type %s"
                                % (type(arg).__name__,))
        else:
            flags = []
            for x in args:
                if isinstance(x, cls):
                    flags.append(int(x))
                elif isinstance(x, int):
                    warnings.warn(
                        "creating CompilerFlags from integers is deprecated, "
                        " flags values change between Python versions. If you are sure use .from_int",
                        DeprecationWarning,
                        stacklevel=2,
                    )
                    flags.append(x)
                elif isinstance(x, str):
                    flags.append(int(cls(x)))
                else:
                    raise ValueError

            #assert flags == [0x10000, 0x8000], flags

            return cls.from_int(reduce(operator.or_, flags))

    @classmethod
    def from_int(cls, arg):
        if arg == -1:
            return cls._UNKNOWN  # Instance optimization
        if arg == 0:
            return cls._ZERO # Instance optimization
        self = int.__new__(cls, arg)
        bad_flags = int(self) & ~_ALL_FLAGS
        if bad_flags:
            raise ValueError(
                "CompilerFlags: unknown flag value(s) %s %s" % (bin(bad_flags), hex(bad_flags)))
        return self

    @classmethod
    def from_str(cls, arg:str):
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
    def names(self) -> Tuple[str, ...]:
        return tuple(
            n
            for f, n in _FLAGNAME_ITEMS
            if f & self)

    def __or__(self, o):
        if o == 0:
            return self
        if not isinstance(o, CompilerFlags):
            o = CompilerFlags(o)
        if self == 0:
            return o
        return CompilerFlags.from_int(int(self) | int(o))

    def __ror__(self, o):
        return self | o

    def __and__(self, o):
        if not isinstance(o, int):
            o = CompilerFlags(o)
        return CompilerFlags.from_int(int(self) & int(o))

    def __rand__(self, o):
        return self & o

    def __xor__(self, o):
        if not isinstance(o, CompilerFlags):
            o = CompilerFlags.from_int(o)
        return CompilerFlags.from_int(int(self) ^ int(o))

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
CompilerFlags._UNKNOWN = int.__new__(CompilerFlags, -1)

# flags that _may_ exists on future versions.
_future_flags = {
    "nested_scopes",
    "generators",
    "division",
    "absolute_import",
    "with_statement",
    "print_function",
    "unicode_literals",
    "barry_as_FLUFL",
    "generator_stop",
    "annotations",
    "allow_top_level_await",
    "only_ast",
    "type_comments",
}
for k in _future_flags:
    setattr(CompilerFlags, k, CompilerFlags._UNKNOWN)

for k, v in _NAME2FLAG.items():
    setattr(CompilerFlags, k, CompilerFlags.from_int(v))
