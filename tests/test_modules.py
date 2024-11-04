# pyflyby/test_modules.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/




import logging.handlers
from   pyflyby._file            import Filename
from   pyflyby._idents          import DottedIdentifier
from   pyflyby._modules         import ModuleHandle
import re
import subprocess
import sys
from   textwrap                 import dedent

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
