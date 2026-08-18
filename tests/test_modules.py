# pyflyby/test_modules.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

import hashlib
import json
import logging.handlers
import os
import pathlib
from   pkgutil                  import iter_modules
from   pyflyby._file            import Filename
from   pyflyby._idents          import DottedIdentifier
from   pyflyby._log             import logger
from   pyflyby._modules         import (ModuleHandle, _fast_iter_modules,
                                        _iter_file_finder_modules,
                                        rebuild_import_cache)
import re
import subprocess
import sys
from   tempfile                 import TemporaryDirectory
from   textwrap                 import dedent
from   unittest                 import mock

import pytest

def test_ModuleHandle_1():
    m = ModuleHandle("sys")
    assert m.name == DottedIdentifier("sys")


def test_ModuleHandle_dotted_1():
    m = ModuleHandle("logging.handlers")
    assert m.name == DottedIdentifier("logging.handlers")


def test_ModuleHandle_from_module_1():
    m = ModuleHandle(logging.handlers)
    assert m == ModuleHandle("logging.handlers")
    assert m.name == DottedIdentifier("logging.handlers")


def test_eqne_1():
    m1a = ModuleHandle("foo.bar")
    m1b = ModuleHandle("foo.bar")
    m2  = ModuleHandle("foo.baz")
    assert     (m1a == m1b)
    assert not (m1a != m1b)
    assert not (m1a == m2)
    assert     (m1a != m2)


def test_filename_1():
    fn = logging.handlers.__file__
    fn = Filename(re.sub("[.]pyc$", ".py", fn)).real
    m = ModuleHandle("logging.handlers")
    assert m.filename.real == fn
    assert m.filename.base == "handlers.py"


def test_filename_init_1():
    fn = logging.__file__
    fn = Filename(re.sub("[.]pyc$", ".py", fn)).real
    m = ModuleHandle("logging")
    assert m.filename.real == fn
    assert m.filename.base == "__init__.py"


def test_module_1():
    m = ModuleHandle("logging")
    assert m.module is logging


# decimal used to be in there, but pytest + coverage seem to inject decimal
# in sys.modules
@pytest.mark.parametrize('modname', ['statistics', 'netrc'])
def test_filename_noload_1(modname):

    # PRE_TEST

    # Here we make sure that everything works properly before the actual test to
    # not get false positive


    # ensure there is no problem with sys.exit itself.
    ret = subprocess.run([sys.executable, '-c', dedent('''
        import sys
        sys.exit(0)
        ''')], capture_output=True)
    assert ret.returncode == 0, (ret, ret.stdout, ret.stderr)

    # Ensure there is no error with pyflyby itself
    ret = subprocess.run([sys.executable, '-c', dedent(f'''
        from pyflyby._modules import ModuleHandle
        import sys
        ModuleHandle("{modname}").filename
        sys.exit(0)
        ''')], capture_output=True)
    assert ret.returncode == 0, (ret, ret.stdout, ret.stderr)

    # ACTUAL TEST

    # don't exit with 1, as something else may exit with 1.
    ret = subprocess.run([sys.executable, '-c', dedent(f'''
        import sys
        if "{modname}" in sys.modules:
            sys.exit(120)
        from pyflyby._modules import ModuleHandle
        if "{modname}" in sys.modules:
            sys.exit(121)
        ModuleHandle("{modname}").filename
        if "{modname}" in sys.modules:
            sys.exit(123)
        else:
            sys.exit(0)
    ''')], capture_output=True)
    assert ret.returncode != 121, f"{modname} imported by pyflyby import"
    assert ret.returncode != 120, f"{modname} in sys.modules at startup"
    assert ret.returncode == 0, (ret, ret.stdout, ret.stderr)


def test_fast_iter_modules():
    """Test that the cpp extension finds the same modules as pkgutil.iter_modules."""
    fast = sorted(list(_fast_iter_modules()), key=lambda x: x.name)
    slow = sorted(list(iter_modules()), key=lambda x: x.name)

    assert fast == slow

@mock.patch.dict(os.environ, {"PYFLYBY_SUPPRESS_CACHE_REBUILD_LOGS": "0"})
@mock.patch("platformdirs.user_cache_dir")
def test_import_cache(mock_user_cache_dir, tmp_path):
    """Test that the import cache is built when iterating modules.

    Also:
    - Check that each path mentioned in the logs appears (sha256-encoded) in the cache
    - The first time generating the import cache, _iter_file_finder_modules is called
    - Subsequent calls use the cached modules
    - If the mtime of one of the importer paths is updated, the corresponding
      cache file gets regenerated
    """

    mock_user_cache_dir.return_value = tmp_path

    assert len(list(tmp_path.iterdir())) == 0
    with (
        mock.patch("pyflyby._modules.logger", wraps=logger) as mock_logger,
        mock.patch(
            "pyflyby._modules._iter_file_finder_modules",
            wraps=_iter_file_finder_modules,
        ) as mock_iffm,
    ):
        list(_fast_iter_modules())

    paths = [str(path.name) for path in tmp_path.iterdir()]
    n_cached_paths = len(paths)
    n_log_messages = len(mock_logger.info.call_args_list)

    # On the first call, log messages should be generated for each import path. Check
    # that _iter_file_finder_modules was called once for each cached path.
    assert (n_cached_paths == n_log_messages) and n_cached_paths > 0
    assert len(mock_iffm.call_args_list) == n_cached_paths
    assert "Rebuilding cache for " in mock_logger.info.call_args.args[0]
    for call_args in mock_logger.info.call_args_list:
        # Grab the path names from the log messages; make sure the sha256 checksum
        # can be found in the paths of the cache directory
        path = pathlib.Path(
            call_args.args[0].lstrip("Rebuilding cache for ").rstrip("...")
        ).expanduser()
        assert hashlib.sha256(str(path).encode()).hexdigest() in paths

    with (
        mock.patch("pyflyby._modules.logger", wraps=logger) as mock_logger,
        mock.patch(
            "pyflyby._modules._iter_file_finder_modules",
            wraps=_iter_file_finder_modules,
        ) as mock_iffm,
    ):
        list(_fast_iter_modules())

    # On the second call, no additional messages should be emitted because the cache has
    # already been built. Check that _iter_file_finder_modules was never called.
    n_log_messages = len(mock_logger.info.call_args_list)
    assert n_log_messages == 0
    mock_iffm.assert_not_called()

    # Update the mtime of one of the importer paths
    path.touch()
    with (
        mock.patch("pyflyby._modules.logger", wraps=logger) as mock_logger,
        mock.patch(
            "pyflyby._modules._iter_file_finder_modules",
            wraps=_iter_file_finder_modules,
        ) as mock_iffm,
    ):
        list(_fast_iter_modules())

    # Only one path should have been updated and only 1 message logged. The number
    # of cache directories should not change.
    assert len(mock_logger.info.call_args_list) == 1
    assert len(list(tmp_path.iterdir())) == n_cached_paths
    mock_iffm.assert_called_once()

    # Regression: when the importer's mtime changes, a new <mtime_ns> cache file
    # is written and the stale one must be removed.  Otherwise stale cache files
    # (which are files, not dirs, inside the per-importer cache directory)
    # accumulate without bound.  `path` here is the importer whose mtime we just
    # bumped; its cache directory should hold exactly the one current file.
    touched_cache_dir = tmp_path / hashlib.sha256(str(path).encode()).hexdigest()
    assert len(list(touched_cache_dir.iterdir())) == 1

@mock.patch.dict(os.environ, {"PYFLYBY_DISABLE_CACHE": "1"})
@mock.patch("platformdirs.user_cache_dir")
def test_import_perms(mock_user_cache_dir, tmp_path):
    """Test that the import cache does not fail on unreadable paths."""

    mock_user_cache_dir.return_value = tmp_path

    with TemporaryDirectory(suffix="_pyflyby_restricted") as restricted:
        try:
            os.chmod(restricted, 0o000)

            sys.path.append(restricted)

            list(_fast_iter_modules())
        finally:
            sys.path.remove(restricted)


@mock.patch("platformdirs.user_cache_dir")
def test_rebuild_import_cache(mock_user_cache_dir, tmp_path):
    """rebuild_import_cache() clears existing cache directories and repopulates."""
    mock_user_cache_dir.return_value = tmp_path
    # Seed a stale cache directory; rebuild should remove it.
    stale = tmp_path / "deadbeef"
    stale.mkdir()
    (stale / "modules.json").write_text("{}")
    with mock.patch("pyflyby._modules._fast_iter_modules") as mock_fim:
        rebuild_import_cache()
    assert not stale.exists()      # stale cache dir removed
    mock_fim.assert_called_once()  # cache repopulated


@mock.patch("platformdirs.user_cache_dir")
def test_rebuild_import_cache_missing_dir(mock_user_cache_dir, tmp_path):
    """rebuild_import_cache() doesn't crash when the cache dir doesn't exist yet."""
    mock_user_cache_dir.return_value = tmp_path / "does_not_exist"
    with mock.patch("pyflyby._modules._fast_iter_modules") as mock_fim:
        rebuild_import_cache()  # must not raise FileNotFoundError
    mock_fim.assert_called_once()


def test_submodules_oserror_fallback():
    """When pkgutil.iter_modules raises OSError, ModuleHandle.submodules falls
    back to _my_iter_modules, which is robust to inaccessible paths."""
    import pkgutil
    mh = ModuleHandle("email")
    # submodules is a cached_property on a cached ModuleHandle; evict any
    # previously-computed value so it recomputes under the patch below.
    mh.__dict__.pop("submodules", None)
    with mock.patch.object(pkgutil, "iter_modules", side_effect=OSError("boom")):
        submodules = mh.submodules
    names = {str(m.name) for m in submodules}
    # email.mime is a subpackage, exercising _my_iter_modules' package branch.
    assert "email.mime" in names


def _exports(importset):
    """Member names of an `ImportSet`, or None."""
    if importset is None:
        return None
    return {imp.split.member_name for imp in importset.imports}


def _star_binds(modname):
    """Independent oracle: what `from <modname> import *` actually binds."""
    ns: dict = {}
    exec("from %s import *" % modname, ns)
    return {k for k in ns if k != "__builtins__"}


def test_exports_static_1():
    assert _exports(ModuleHandle("json").exports) == set(json.__all__)


def test_runtime_exports_dynamic_all_1(dynamic_all_module):
    """A run-time __all__ is invisible statically but seen by importing."""
    mh = ModuleHandle(dynamic_all_module)
    assert mh.exports is None
    assert _exports(mh.runtime_exports) == {"alpha", "beta"}


def test_get_exports_allow_exec_1(dynamic_all_module):
    mh = ModuleHandle(dynamic_all_module)
    assert mh.get_exports(allow_exec=False) is None
    assert _exports(mh.get_exports(allow_exec=True)) == {"alpha", "beta"}


def test_get_exports_no_allow_exec_does_not_exec_1(tmp_module):
    """allow_exec=False must not execute the module itself."""
    marker = tmp_module.path / "imported.marker"
    name = tmp_module("pyflyby_test_notimported_20947731", """
        import pathlib
        pathlib.Path(%r).write_text("yes")
        alpha = 1
    """ % str(marker))
    assert _exports(ModuleHandle(name).get_exports(allow_exec=False)) == {"alpha"}
    assert not marker.exists()
    assert name not in sys.modules


def test_get_exports_prefers_runtime_over_lossy_static_1(tmp_module):
    """
    Static analysis omits names re-exported from unrelated modules, which a
    star import does bind, so a non-empty static result must not win.
    """
    helper = tmp_module("pyflyby_test_lossy_helper_38104772",
                        "def sqrt(x): return 'MY-SQRT'\n")
    lib = tmp_module("pyflyby_test_lossy_lib_38104772", """
        from %s import sqrt
        def alpha(): pass
    """ % helper)
    mh = ModuleHandle(lib)
    assert _exports(mh.exports) == {"alpha"}
    assert _exports(mh.get_exports(allow_exec=True)) == {"alpha", "sqrt"}


def test_get_exports_falls_back_to_static_when_import_fails_1(tmp_module):
    """If the import blows up, fall back to what static analysis found."""
    name = tmp_module("pyflyby_test_importfail_60355218", """
        def alpha(): pass
        raise RuntimeError("boom")
    """)
    assert _exports(ModuleHandle(name).get_exports(allow_exec=True)) == {"alpha"}


@pytest.mark.parametrize("modname", ["math", "sys", "itertools"])
def test_get_exports_extension_module_1(modname):
    """Builtins have no source, so static analysis raises rather than empties."""
    mh = ModuleHandle(modname)
    with pytest.raises(Exception):
        mh.get_exports(allow_exec=False)
    assert _exports(mh.get_exports(allow_exec=True)) == _star_binds(modname)



@pytest.mark.parametrize("source,expected,star_legal", [
    pytest.param("""
        visible = 1
        _hidden = 2
    """, {"visible"}, True, id="no-dunder-all"),
    # A PEP-562 __dir__ misreports what a star import binds; we use __dict__.
    pytest.param("""
        realname = 1
        def __dir__(): return ["lazyname"]
        def __getattr__(n):
            if n == "lazyname": return 2
            raise AttributeError(n)
    """, {"realname"}, True, id="dunder-dir"),
    pytest.param("""
        alpha = 1
        __all__ = list([])
    """, None, False, id="nothing-exported"),
])
def test_runtime_exports_1(tmp_module, source, expected, star_legal):
    name = tmp_module("pyflyby_test_runtime_exports_75330184", source)
    assert _exports(ModuleHandle(name).runtime_exports) == expected
    if star_legal:
        # Cross-check against what Python itself binds.
        assert _star_binds(name) == expected


def test_runtime_exports_submodule_in_all_1(tmp_module):
    """A submodule named in __all__ is exported even if not imported yet."""
    pkg = tmp_module("pyflyby_test_pkg_submod_57390142", """
        def _mk(): return ["submod", "alpha"]
        __all__ = _mk()
        alpha = 1
    """, package=True)
    (tmp_module.path / pkg / "submod.py").write_text("x = 1\n")
    assert _exports(ModuleHandle(pkg).runtime_exports) == {"alpha", "submod"}


def test_runtime_exports_all_lists_missing_name_1(tmp_module):
    """__all__ is taken at its word; a real star import would fail the same."""
    name = tmp_module("pyflyby_test_bad_all_16608259", """
        real = 1
        __all__ = list(["real", "nonexistent"])
    """)
    assert _exports(ModuleHandle(name).runtime_exports) == {"real", "nonexistent"}


def test_runtime_exports_non_string_all_1(tmp_module):
    """A malformed __all__ raises, so `get_exports` falls back to static."""
    name = tmp_module("pyflyby_test_badall_type_11947503", """
        alpha = 1
        __all__ = list(["alpha", 42])
    """)
    mh = ModuleHandle(name)
    with pytest.raises(Exception):
        mh.runtime_exports
    assert "alpha" in _exports(mh.get_exports(allow_exec=True))


