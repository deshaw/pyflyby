
# Some self tests to check that our test setup is pointing to wrong paths etc.



import os
import pytest
import subprocess
import sys

import pyflyby


def pipe(command, stdin=""):
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    ).communicate(stdin)[0].strip().decode('utf-8')


def test_pytest_version_1():
    pytest_version = tuple(map(int, pytest.__version__.split(".")[:2]))
    if pytest_version < (2, 4):
        raise AssertionError("test cases require pytest >= 2.4; "
                             "your version is pytest %s", pytest.__version__)


def test_pyflyby_version_1():
    # Check that the version that we've imported here is the same as the one
    # in this repository.
    PYFLYBY_HOME   = os.path.dirname(os.path.abspath(os.path.dirname(__file__)))
    PYFLYBY_PYPATH = os.path.join(PYFLYBY_HOME, "lib/python")
    version_vars = {}
    version_fn = os.path.join(PYFLYBY_PYPATH, "pyflyby/_version.py")
    exec(open(version_fn).read(), {}, version_vars)
    expected = version_vars["__version__"]
    result = pyflyby.__version__
    assert expected == result


def test_pyflyby_tox_path_1():
    # If we're inside tox, then check that we've loaded the virtualenv version.
    if '/.tox/' not in sys.prefix:
        return
    assert pyflyby.__file__.startswith(os.path.normpath(sys.prefix))


def test_pyflyby_subprocess_file_1():
    # Check that our test setup is getting the right pyflyby.
    cmd = "import os, pyflyby; print(os.path.realpath(pyflyby.__file__))"
    result = pipe([sys.executable, '-c', cmd]).replace(".pyc", ".py")
    expected = os.path.realpath(pyflyby.__file__).replace(".pyc", ".py")
    assert expected == result


def test_pyflyby_subprocess_version_1():
    # Check that our test setup is getting the right pyflyby.
    cmd = "import pyflyby; print(pyflyby.__version__)"
    result = pipe([sys.executable, '-c', cmd])
    expected = pyflyby.__version__
    assert expected == result
