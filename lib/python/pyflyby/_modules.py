# pyflyby/_modules.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import annotations

import ast
from   functools                import cached_property, total_ordering
import hashlib
import importlib
import itertools
import json
import os
import pathlib
import pkgutil
import platformdirs
import textwrap

from   pyflyby._fast_iter_modules \
                                import _iter_file_finder_modules
from   pyflyby._file            import FileText, Filename
from   pyflyby._idents          import DottedIdentifier, is_identifier
from   pyflyby._log             import logger
from   pyflyby._util            import (ExcludeImplicitCwdFromPathCtx, cmp,
                                        memoize, prefixes)

import re
import shutil
import sys
import types
from   typing                   import Any, Dict, Generator, Union

class ErrorDuringImportError(ImportError):
    """
    Exception raised by import_module if the module exists but an exception
    occurred while attempting to import it.  That nested exception could be
    ImportError, e.g. if a module tries to import another module that doesn't
    exist.
    """

def rebuild_import_cache():
    """Force the import cache to be rebuilt.

    The cache is deleted before calling _fast_iter_modules, which repopulates the cache.
    """
    for path in pathlib.Path(
        platformdirs.user_cache_dir(appname='pyflyby', appauthor=False)
    ).iterdir():
        _remove_import_cache_dir(path)
    _fast_iter_modules()


def _remove_import_cache_dir(path: pathlib.Path):
    """Remove an import cache directory.

    Import cache directories exist in <user cache dir>/pyflyby/, and they should
    contain just a single file which itself contains a JSON blob of cached import names.
    We therefore only delete the requested path if it is a directory.

    Parameters
    ----------
    path : pathlib.Path
        Import cache directory path to remove
    """
    if path.is_dir():
        # Only directories are valid import cache entries
        try:
            shutil.rmtree(str(path))
        except Exception as e:
            logger.error(
                f"Failed to remove cache directory at {path} - please "
                "consider removing this directory manually. Error:\n"
                f"{textwrap.indent(str(e), prefix='  ')}"
            )


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
        raise ErrorDuringImportError(
            "Error while attempting to import %s: %s: %s"
            % (module_name, type(e).__name__, e)) from e
    except Exception as e:
        raise ErrorDuringImportError(
            "Error while attempting to import %s: %s: %s"
            % (module_name, type(e).__name__, e)) from e


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

    name: DottedIdentifier

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, Filename):
            return cls._from_filename(arg)
        if isinstance(arg, (str, DottedIdentifier)):
            return cls._from_modulename(arg)
        if isinstance(arg, types.ModuleType):
            return cls._from_module(arg)
        raise TypeError("ModuleHandle: unexpected %s" % (type(arg).__name__,))

    _cls_cache:Dict[Any, Any] = {}

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

    @cached_property
    def parent(self):
        if not self.name.parent:
            return None
        return ModuleHandle(self.name.parent)

    @cached_property
    def ancestors(self):
        return tuple(ModuleHandle(m) for m in self.name.prefixes)

    @cached_property
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

    @cached_property
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

        import importlib.util
        find = importlib.util.find_spec

        try:
            pkg = find(name)
        except Exception:
            # Catch all exceptions, not just ImportError.  If the __init__.py
            # for the parent package of the module raises an exception, it'll
            # propagate to here.
            pkg = None
        return pkg is not None

    @cached_property
    def filename(self):
        """
        Return the filename, if appropriate.

        The module itself will not be imported, but if the module is not a
        top-level module/package, accessing this attribute may cause the
        parent package to be imported.

        :rtype:
          `Filename`
        """
        if sys.version_info > (3, 12):
            from importlib.util import find_spec
            try:
                mod = find_spec(str(self.name))
                if mod is None or mod.origin is None:
                    return None
                else:
                    assert isinstance(mod.origin, str)
                    return Filename(mod.origin)
            except ModuleNotFoundError:
                return None
            assert False

        # Use the loader mechanism to find the filename.  We do so instead of
        # using self.module.__file__, because the latter forces importing a
        # module, which may be undesirable.

        import pkgutil
        try:
             #TODO: deprecated and will be removed in 3.14
            loader = pkgutil.get_loader(str(self.name))
        except ImportError:
            return None
        if not loader:
            return None
        # Get the filename using loader.get_filename().  Note that this does
        # more than just loader.filename: for example, it adds /__init__.py
        # for packages.
        if not hasattr(loader, 'get_filename'):
            return None
        filename = loader.get_filename()
        if not filename:
            return None
        return Filename(pyc_to_py(filename))

    @cached_property
    def text(self):
        return FileText(self.filename)

    def __text__(self):
        return self.text

    @cached_property
    def block(self):
        from pyflyby._parse import PythonBlock
        return PythonBlock(self.text)

    @staticmethod
    @memoize
    def list() -> list[str]:
        """Enumerate all top-level packages/modules.

        The current working directory is excluded for autoimporting; if we autoimported
        random python scripts in the current directory, we could accidentally execute
        code with side effects.

        Also exclude any module names that are not legal python module names (e.g.
        "try.py" or "123.py").

        :return: A list of all importable module names
        """
        with ExcludeImplicitCwdFromPathCtx():
            return [mod.name for mod in _fast_iter_modules() if is_identifier(mod.name)]

    @cached_property
    def submodules(self):
        """
        Enumerate the importable submodules of this module.

          >>> ModuleHandle("email").submodules      # doctest:+ELLIPSIS
          (..., ModuleHandle('email.encoders'), ..., ModuleHandle('email.mime'), ...)

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

    @staticmethod
    def _member_from_node(node):
        extractors = {
            # Top-level assignments (as opposed to member assignments
            # whose targets are of type ast.Attribute).
            ast.Assign: lambda x: [t.id for t in x.targets if isinstance(t, ast.Name)],
            ast.ClassDef: lambda x: [x.name],
            ast.FunctionDef: lambda x: [x.name],
        }
        if isinstance(node, tuple(extractors.keys())):
            return extractors[type(node)](node)
        return []

    @cached_property
    def exports(self):
        """
        Get symbols exported by this module.

        Note that this will not recognize symbols that are dynamically
        introduced to the module's namespace or __all__ list.

        :rtype:
          `ImportSet` or ``None``
        :return:
          Exports, or ``None`` if nothing exported.
        """
        from pyflyby._importclns import ImportStatement, ImportSet

        filename = getattr(self, 'filename', None)
        if not filename or not filename.exists:
            # Try to load the module to get the filename
            filename = Filename(self.module.__file__)
        text = FileText(filename)

        ast_mod = ast.parse(str(text), str(filename)).body

        # First, add members that are explicitly defined in the module
        members = list(itertools.chain(*[self._member_from_node(n) \
                                         for n in ast_mod]))

        # If __all__ is defined, try to use it
        all_is_good = False  # pun intended
        all_members = []
        if "__all__" in members:
            # Iterate through the nodes and reconstruct the
            # value of __all__
            for n in ast_mod:
                if isinstance(n, ast.Assign):
                    if "__all__" in self._member_from_node(n):
                        try:
                            all_members = list(ast.literal_eval(n.value))
                            all_is_good = True
                        except (ValueError, TypeError):
                            all_is_good = False
                elif isinstance(n, ast.AugAssign) and \
                     isinstance(n.target, ast.Name) and \
                     n.target.id == "__all__" and all_is_good:
                    try:
                        all_members += list(ast.literal_eval(n.value))
                    except (ValueError, TypeError):
                        all_is_good = False
            if not all(type(s) == str for s in members):
                raise Exception(
                    "Module %r contains non-string entries in __all__"
                    % (str(self.name),))

        if all_is_good:
            members = all_members
        else:
            # Add "from" imports that belong to submodules
            # (note: this will fail to recognize implicit relative imports)
            imp_nodes = [n for n in ast_mod if isinstance(n, ast.ImportFrom)]
            for imp_node in imp_nodes:
                if imp_node.level == 0:
                    from_mod = DottedIdentifier(imp_node.module)
                    if not from_mod.startswith(self.name):
                        continue
                elif imp_node.level == 1 and \
                     filename.base == "__init__.py":
                    # Special case: a relative import can be from a submodule only if
                    # our module's filename is  __init__.py.
                    from_mod = self.name
                    if imp_node.module:
                        from_mod += imp_node.module
                else:
                    continue
                for n in imp_node.names:
                    m  = n.asname or n.name
                    if n.name != "*" and not ModuleHandle(from_mod + m).exists:
                        members.append(m)

        # Filter by non-private.
        members = [n for n in members if not n.startswith("_")]

        # Filter out artificially added "deep" members.
        members = tuple([(n, None) for n in members if "." not in n])
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
        # TODO: as far as I can tell the code here is never reached, or haven't
        # been in quite some time as the line below was invalid on Python 3 since 2011
        # zip(...)[...] fails as zip is not indexable.
        # the only place that seem to be using this method is XrefScanner.
        for part, prefix in list(zip(identifier, prefixes(identifier)))[1:]:
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


def _format_path(path: Union[str, pathlib.Path]) -> str:
    """Format a path for printing as a log message.

    If the path is a child of $HOME, the prefix is replaced with "~" for brevity.
    Otherwise the original path is returned.

    Parameters
    ----------
    path : Union[str, pathlib.Path]
        Path to format

    Returns
    -------
    str
        Formatted output path
    """
    path = pathlib.Path(path)
    home = pathlib.Path.home()

    if path.is_relative_to(home):
        return str(pathlib.Path("~").joinpath(path.relative_to(home)))
    return str(path)


SUFFIXES = sorted(importlib.machinery.all_suffixes())


def _cached_module_finder(
    importer: importlib.machinery.FileFinder, prefix: str = ""
) -> Generator[tuple[str, bool], None, None]:
    """Yield the modules found by the importer.

    The importer path's mtime is recorded; if the path and mtime have a corresponding
    cache file, the modules recorded in the cache file are returned. Otherwise, the
    cache is rebuilt.

    Parameters
    ----------
    importer : importlib.machinery.FileFinder
        FileFinder importer that points to a path under which imports can be found
    prefix : str
        String to affix to the beginning of each module name

    Returns
    -------
    Generator[tuple[str, bool], None, None]
        Tuples containing (prefix+module name, a bool indicating whether the module is a
        package or not)
    """
    if os.environ.get("PYFLYBY_DISABLE_CACHE", "0") == "1":
        modules = _iter_file_finder_modules(importer, SUFFIXES)
        for module, ispkg in modules:
            yield prefix + module, ispkg
        return

    cache_dir = pathlib.Path(
        platformdirs.user_cache_dir(appname='pyflyby', appauthor=False)
    ) / hashlib.sha256(str(importer.path).encode()).hexdigest()
    cache_file = cache_dir / str(os.stat(importer.path).st_mtime_ns)

    if cache_file.exists():
        with open(cache_file) as fp:
            modules = json.load(fp)
    else:
        # Generate the cache dir if it doesn't exist, and remove any existing cache
        # files for the given import path
        cache_dir.mkdir(parents=True, exist_ok=True)
        for path in cache_dir.iterdir():
            _remove_import_cache_dir(path)

        if os.environ.get("PYFLYBY_SUPPRESS_CACHE_REBUILD_LOGS", "1") != "1":
            logger.info(f"Rebuilding cache for {_format_path(importer.path)}...")

        modules = _iter_file_finder_modules(importer, SUFFIXES)
        with open(cache_file, 'w') as fp:
            json.dump(modules, fp)

    for module, ispkg in modules:
        yield prefix + module, ispkg


def _fast_iter_modules() -> Generator[pkgutil.ModuleInfo, None, None]:
    """Return an iterator over all importable python modules.

    This function patches `pkgutil.iter_importer_modules` for
    `importlib.machinery.FileFinder` types, causing `pkgutil.iter_importer_modules` to
    call our own custom _iter_file_finder_modules instead of
    pkgutil._iter_file_finder_modules.

    :return: The modules that are importable by python
    """
    pkgutil.iter_importer_modules.register(  # type: ignore[attr-defined]
        importlib.machinery.FileFinder, _cached_module_finder
    )
    yield from pkgutil.iter_modules()
    pkgutil.iter_importer_modules.register(  # type: ignore[attr-defined]
        importlib.machinery.FileFinder,
        pkgutil._iter_file_finder_modules,  # type: ignore[attr-defined]
    )
