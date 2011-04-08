
from __future__ import absolute_import, division, with_statement

import ast
import re
import types

from   pyflyby.file             import FileLines, Filename, read_file
from   pyflyby.log              import logger
from   pyflyby.util             import cached_attribute, memoize, prefixes

@memoize
def import_module(module_name):
    module_name = str(module_name)
    logger.debug("Importing %r", module_name)
    try:
        result = __import__(module_name, fromlist=['dummy'])
        assert result.__name__ == module_name
        return result
    except Exception as e:
        logger.debug("Failed to import %r: %s: %r",
                     module_name, type(e).__name__, e)
        raise


def pyc_to_py(filename):
    if filename.endswith(".pyc") or filename.endswith(".pyo"):
        filename = filename[:-1]
    return filename


class BadSymbolNameError(ValueError):
    pass


class SymbolName(object):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, basestring):
            return cls.from_name(arg)
        if isinstance(arg, (tuple, list)):
            return cls.from_name(".".join(arg))
        raise TypeError

    @classmethod
    def from_name(cls, name):
        self = object.__new__(cls)
        self.name = str(name)
        self.parts = tuple(self.name.split('.'))
        if not self.parts:
            raise BadSymbolNameError("Empty symbol name")
        for part in self.parts:
            if not re.match("^[a-zA-Z_][a-zA-Z0-9_]*$", part):
                raise BadSymbolNameError("Invalid python symbol name %r" % (name,))
        return self

    def startswith(self, o):
        o = type(self)(o)
        return self.parts[:len(o.parts)] == o.parts

    def __getitem__(self, x):
        return type(self)(self.parts[x])

    def __len__(self):
        return len(self.parts)

    def __iter__(self):
        return (type(self)(x) for x in self.parts)

    def __add__(self, suffix):
        return type(self)("%s.%s") % (self, suffix)

    def __str__(self):
        return self.name

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.name)

    def __hash__(self):
        return hash(self.name)

    def __cmp__(self, other):
        return cmp(self.name, type(self)(other).name)


class Module(object):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, Filename):
            return cls.from_filename(arg)
        if isinstance(arg, (str, SymbolName)):
            return cls.from_modulename(arg)
        if isinstance(arg, types.ModuleType):
            return cls.from_module(arg)
        raise TypeError

    @classmethod
    def from_modulename(cls, modulename):
        self = object.__new__(cls)
        self.name = SymbolName(modulename)
        return self

    @classmethod
    def from_module(cls, module):
        if not isinstance(module, types.ModuleType):
            raise TypeError
        self = cls.from_modulename(module.__name__)
        assert self.module is module
        return self

    @classmethod
    def from_filename(cls, filename):
        filename = Filename(filename)
        raise NotImplementedError(
            "TODO: look at sys.path to guess module name")

    @cached_attribute
    def module(self):
        return import_module(self.name)

    @cached_attribute
    def filename(self):
        return Filename(pyc_to_py(self.module.__file__))

    @cached_attribute
    def file_contents(self):
        return read_file(self.filename)

    @cached_attribute
    def file_lines(self):
        return FileLines(self.file_contents)

    @cached_attribute
    def ast(self):
        return ast.parse(str(self.file_contents), str(self.filename))

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, str(self.name))

    def __hash__(self):
        return hash(self.name)

    def __cmp__(self, o):
        return cmp(self.name, Module(o).name)

    def __getitem__(self, x):
        if isinstance(x, slice):
            return type(self)(self.name[x])
        raise TypeError

    def __len__(self):
        return len(self.name)

    def startswith(self, o):
        return self.name.startswith(type(self)(o).name)

    @classmethod
    def containing(cls, identifier):
        """
        Try to find the module that defines a name such as C{a.b.c} by trying
        to import C{a}, C{a.b}, and C{a.b.c}.

        @return:
          The name of the 'deepest' module (most commonly it would be C{a.b}
          in this example).
        @rtype:
          L{Module}
        """
        # In the code below we catch "Exception" rather than just ImportError
        # or AttributeError since importing and __getattr__ing can raise other
        # exceptions.
        identifier = SymbolName(identifier)
        try:
            module = Module(identifier[:1])
            result = module.module
        except Exception as e:
            raise ImportError(e)
        for part, prefix in zip(identifier, prefixes(identifier))[1:]:
            try:
                result = getattr(result, str(part))
            except Exception:
                try:
                    module = cls(prefix)
                    result = module.module
                except Exception as e:
                    raise ImportError(e)
            else:
                if isinstance(result, types.ModuleType):
                    module = cls(result)
        logger.debug("Imported %r to get %r", module, identifier)
        return module
