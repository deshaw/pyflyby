# pyflyby/_modules.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

from   functools                import total_ordering
import os
import re
import six
from   six                      import reraise
import sys
import types

from   pyflyby._file            import FileText, Filename
from   pyflyby._idents          import DottedIdentifier, is_identifier
from   pyflyby._log             import logger
from   pyflyby._util            import (ExcludeImplicitCwdFromPathCtx,
                                        cached_attribute, cmp, memoize,
                                        prefixes)


class ErrorDuringImportError(ImportError):
    """
    Exception raised by import_module if the module exists but an exception
    occurred while attempting to import it.  That nested exception could be
    ImportError, e.g. if a module tries to import another module that doesn't
    exist.
    """


@memoize
def import_module(module_name):
    module_name = str(module_name)
    logger.debug("Importing %r", module_name)
    try:
        result = __import__(module_name, fromlist=['dummy'])
        if result.__name__ != module_name:
            logger.debug("Note: import_module(%r).__name__ == %r",
                         module_name, result.__name__)
        return result
    except ImportError as e:
        # We got an ImportError.  Figure out whether this is due to the module
        # not existing, or whether the module exists but caused an ImportError
        # (perhaps due to trying to import another problematic module).
        # Do this by looking at the exception traceback.  If the previous
        # frame in the traceback is this function (because locals match), then
        # it should be the internal import machinery reporting that the module
        # doesn't exist.  Re-raise the exception as-is.
        # If some sys.meta_path or other import hook isn't compatible with
        # such a check, here are some things we could do:
        #   - Use pkgutil.find_loader() after the fact to check if the module
        #     is supposed to exist.  Note that we shouldn't rely solely on
        #     this before attempting to import, because find_loader() doesn't
        #     work with meta_path.
        #   - Write a memoized global function that compares in the current
        #     environment the difference between attempting to import a
        #     non-existent module vs a problematic module, and returns a
        #     function that uses the working discriminators.
        real_importerror1 = type(e) is ImportError
        real_importerror2 = (sys.exc_info()[2].tb_frame.f_locals is locals())
        m = re.match("^No module named (.*)$", str(e))
        real_importerror3 = (m and m.group(1) == module_name
                             or module_name.endswith("."+m.group(1)))
        logger.debug("import_module(%r): real ImportError: %s %s %s",
                     module_name,
                     real_importerror1, real_importerror2, real_importerror3)
        if real_importerror1 and real_importerror2 and real_importerror3:
            raise
        reraise(ErrorDuringImportError(
            "Error while attempting to import %s: %s: %s"
            % (module_name, type(e).__name__, e)), None, sys.exc_info()[2])
    except Exception as e:
        reraise(ErrorDuringImportError(
            "Error while attempting to import %s: %s: %s"
            % (module_name, type(e).__name__, e)), None, sys.exc_info()[2])


def _my_iter_modules(path, prefix=''):
    # Modified version of pkgutil.ImpImporter.iter_modules(), patched to
    # handle inaccessible subdirectories.
    if path is None:
        return
    try:
        filenames = os.listdir(path)
    except OSError:
        return # silently ignore inaccessible paths
    filenames.sort()  # handle packages before same-named modules
    yielded = {}
    import inspect
    for fn in filenames:
        modname = inspect.getmodulename(fn)
        if modname=='__init__' or modname in yielded:
            continue
        subpath = os.path.join(path, fn)
        ispkg = False
        try:
            if not modname and os.path.isdir(path) and '.' not in fn:
                modname = fn
                for fn in os.listdir(subpath):
                    subname = inspect.getmodulename(fn)
                    if subname=='__init__':
                        ispkg = True
                        break
                else:
                    continue    # not a package
        except OSError:
            continue # silently ignore inaccessible subdirectories
        if modname and '.' not in modname:
            yielded[modname] = 1
            yield prefix + modname, ispkg


def pyc_to_py(filename):
    if filename.endswith(".pyc") or filename.endswith(".pyo"):
        filename = filename[:-1]
    return filename


@total_ordering
class ModuleHandle(object):
    """
    A handle to a module.
    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, Filename):
            return cls._from_filename(arg)
        if isinstance(arg, (six.string_types, DottedIdentifier)):
            return cls._from_modulename(arg)
        if isinstance(arg, types.ModuleType):
            return cls._from_module(arg)
        raise TypeError("ModuleHandle: unexpected %s" % (type(arg).__name__,))

    _cls_cache = {}

    @classmethod
    def _from_modulename(cls, modulename):
        modulename = DottedIdentifier(modulename)
        try:
            return cls._cls_cache[modulename]
        except KeyError:
            pass
        self = object.__new__(cls)
        self.name = modulename
        cls._cls_cache[modulename] = self
        return self

    @classmethod
    def _from_module(cls, module):
        if not isinstance(module, types.ModuleType):
            raise TypeError
        self = cls._from_modulename(module.__name__)
        assert self.module is module
        return self

    @classmethod
    def _from_filename(cls, filename):
        filename = Filename(filename)
        raise NotImplementedError(
            "TODO: look at sys.path to guess module name")

    @cached_attribute
    def parent(self):
        if not self.name.parent:
            return None
        return ModuleHandle(self.name.parent)

    @cached_attribute
    def ancestors(self):
        return tuple(ModuleHandle(m) for m in self.name.prefixes)

    @cached_attribute
    def module(self):
        """
        Return the module instance.

        :rtype:
          ``types.ModuleType``
        :raise ErrorDuringImportError:
          The module should exist but an error occurred while attempting to
          import it.
        :raise ImportError:
          The module doesn't exist.
        """
        # First check if prefix component is importable.
        if self.parent:
            self.parent.module
        # Import.
        return import_module(self.name)

    @cached_attribute
    def exists(self):
        """
        Return whether the module exists, according to pkgutil.
        Note that this doesn't work for things that are only known by using
        sys.meta_path.
        """
        name = str(self.name)
        if name in sys.modules:
            return True
        if self.parent and not self.parent.exists:
            return False
        import pkgutil
        try:
            loader = pkgutil.find_loader(name)
        except Exception:
            # Catch all exceptions, not just ImportError.  If the __init__.py
            # for the parent package of the module raises an exception, it'll
            # propagate to here.
            loader = None
        return loader is not None

    @cached_attribute
    def filename(self):
        """
        Return the filename, if appropriate.

        The module itself will not be imported, but if the module is not a
        top-level module/package, accessing this attribute may cause the
        parent package to be imported.

        :rtype:
          `Filename`
        """
        # Use the loader mechanism to find the filename.  We do so instead of
        # using self.module.__file__, because the latter forces importing a
        # module, which may be undesirable.
        import pkgutil
        try:
            loader = pkgutil.get_loader(str(self.name))
        except ImportError:
            return None
        if not loader:
            return None
        # Get the filename using loader.get_filename().  Note that this does
        # more than just loader.filename: for example, it adds /__init__.py
        # for packages.
        filename = loader.get_filename()
        if not filename:
            return None
        return Filename(pyc_to_py(filename))

    @cached_attribute
    def text(self):
        return FileText(self.filename)

    def __text__(self):
        return self.text

    @cached_attribute
    def block(self):
        from pyflyby._parse import PythonBlock
        return PythonBlock(self.text)

    @staticmethod
    @memoize
    def list():
        """
        Enumerate all top-level packages/modules.

        :rtype:
          ``tuple`` of `ModuleHandle` s
        """
        import pkgutil
        # Get the list of top-level packages/modules using pkgutil.
        # We exclude "." from sys.path while doing so.  Python includes "." in
        # sys.path by default, but this is undesirable for autoimporting.  If
        # we autoimported random python scripts in the current directory, we
        # could accidentally execute code with side effects.  If the current
        # working directory is /tmp, trying to enumerate modules there also
        # causes problems, because there are typically directories there not
        # readable by the current user.
        with ExcludeImplicitCwdFromPathCtx():
            modlist = pkgutil.iter_modules(None)
            module_names = [t[1] for t in modlist]
        # pkgutil includes all *.py even if the name isn't a legal python
        # module name, e.g. if a directory in $PYTHONPATH has files named
        # "try.py" or "123.py", pkgutil will return entries named "try" or
        # "123".  Filter those out.
        module_names = [m for m in module_names if is_identifier(m)]
        # Canonicalize.
        return tuple(ModuleHandle(m) for m in sorted(set(module_names)))

    @cached_attribute
    def submodules(self):
        """
        Enumerate the importable submodules of this module.

          >>> ModuleHandle("email").submodules      # doctest:+ELLIPSIS
          (..., 'email.encoders', ..., 'email.mime', ...)

        :rtype:
          ``tuple`` of `ModuleHandle` s
        """
        import pkgutil
        module = self.module
        try:
            path = module.__path__
        except AttributeError:
            return ()
        # Enumerate the modules at a given path.  Prefer to use ``pkgutil`` if
        # we can.  However, if it fails due to OSError, use our own version
        # which is robust to that.
        try:
            submodule_names = [t[1] for t in pkgutil.iter_modules(path)]
        except OSError:
            submodule_names = [t[0] for p in path for t in _my_iter_modules(p)]
        return tuple(ModuleHandle("%s.%s" % (self.name,m))
                     for m in sorted(set(submodule_names)))

    @cached_attribute
    def exports(self):
        """
        Get symbols exported by this module.

        Note that this requires involves actually importing this module, which
        may have side effects.  (TODO: rewrite to avoid this?)

        :rtype:
          `ImportSet` or ``None``
        :return:
          Exports, or ``None`` if nothing exported.
        """
        from pyflyby._importclns import ImportStatement, ImportSet
        module = self.module
        try:
            members = module.__all__
        except AttributeError:
            members = dir(module)
            # Filter by non-private.
            members = [n for n in members if not n.startswith("_")]
            # Filter by definition in the module.
            def from_this_module(name):
                # TODO: could do this more robustly by parsing the AST and
                # looking for STOREs (definitions/assignments/etc).
                x = getattr(module, name)
                m = getattr(x, "__module__", None)
                if not m:
                    return False
                return DottedIdentifier(m).startswith(self.name)
            members = [n for n in members if from_this_module(n)]
        else:
            if not all(type(s) == str for s in members):
                raise Exception(
                    "Module %r contains non-string entries in __all__"
                    % (str(self.name),))
        # Filter out artificially added "deep" members.
        members = [n for n in members if "." not in n]
        if not members:
            return None
        return ImportSet(
            [ ImportStatement.from_parts(str(self.name), members) ])

    def __str__(self):
        return str(self.name)

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, str(self.name))

    def __hash__(self):
        return hash(self.name)

    def __cmp__(self, o):
        if self is o:
            return 0
        if not isinstance(o, ModuleHandle):
            return NotImplemented
        return cmp(self.name, o.name)

    def __eq__(self, o):
        if self is o:
            return True
        if not isinstance(o, ModuleHandle):
            return NotImplemented
        return self.name == o.name

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, o):
        if not isinstance(o, ModuleHandle):
            return NotImplemented
        return self.name < o.name

    def __getitem__(self, x):
        if isinstance(x, slice):
            return type(self)(self.name[x])
        raise TypeError

    @classmethod
    def containing(cls, identifier):
        """
        Try to find the module that defines a name such as ``a.b.c`` by trying
        to import ``a``, ``a.b``, and ``a.b.c``.

        :return:
          The name of the 'deepest' module (most commonly it would be ``a.b``
          in this example).
        :rtype:
          `Module`
        """
        # In the code below we catch "Exception" rather than just ImportError
        # or AttributeError since importing and __getattr__ing can raise other
        # exceptions.
        identifier = DottedIdentifier(identifier)
        try:
            module = ModuleHandle(identifier[:1])
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
