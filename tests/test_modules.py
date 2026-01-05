# pyflyby/test_modules.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

import hashlib
import logging.handlers
import os
import pathlib
from   pkgutil                  import iter_modules
from   pyflyby._file            import Filename
from   pyflyby._idents          import DottedIdentifier
from   pyflyby._log             import logger
from   pyflyby._modules         import (ModuleHandle, _fast_iter_modules,
                                        _iter_file_finder_modules)
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
