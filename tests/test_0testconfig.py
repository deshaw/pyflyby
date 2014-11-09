
# Some self tests to check that our test setup is pointing to wrong paths etc.

from __future__ import absolute_import, division, with_statement

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
    ).communicate(stdin)[0].strip()


def test_pytest_version_1():
    pytest_version = tuple(map(int, pytest.__version__.split(".")[:2]))
    if pytest_version < (2, 4):
        raise AssertionError("test cases require pytest >= 2.4; "
                             "your version is pytest %s", pytest.__version__)


def test_pyflyby_path_1():
    # If we're inside tox, then check that we've loaded the virtualenv version.
    if '/.tox/' not in sys.prefix:
        return
    assert pyflyby.__file__.startswith(os.path.normpath(sys.prefix))


def test_pyflyby_file_1():
    # Check that our test setup is getting the right pyflyby.
    cmd = "import pyflyby; print pyflyby.__file__"
    result = pipe([sys.executable, '-c', cmd]).replace(".pyc", ".py")
    expected = pyflyby.__file__.replace(".pyc", ".py")
    assert result == expected


def test_pyflyby_version_1():
    # Check that our test setup is getting the right pyflyby.
    cmd = "import pyflyby; print pyflyby.__version__"
    result = pipe([sys.executable, '-c', cmd])
    expected = pyflyby.__version__
    assert result == expected
