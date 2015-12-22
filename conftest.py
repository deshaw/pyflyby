

from __future__ import absolute_import, division, with_statement

import os
import sys

_already_ran_setup = False

def pytest_runtest_setup(item):
    """
    Run the logger setup once.
    """
    # Although we only bother doing this once (and never tearDown), we still
    # do this in a pytest_runtest_setup, rather than e.g. pytest_configure()
    # because otherwise tox+py.test can get confused by having already loaded
    # pyflyby from a different location.
    global _already_ran_setup
    if _already_ran_setup:
        return
    _already_ran_setup = True
    _setup_logger()


def pytest_report_header(config):
    import IPython
    print "IPython %s" % (IPython.__version__)
    import pyflyby
    dir = os.path.dirname(pyflyby.__file__)
    print "pyflyby %s from %s" % (pyflyby.__version__, dir)


def _setup_logger():
    """
    Set up the pyflyby logger to be doctest-friendly.
    """
    import logging
    import pyflyby
    import sys
    class TestStream(object):
        def write(self, x):
            sys.stdout.write(x)
            sys.stdout.flush()
        def flush(self):
            pass
    test_handler = logging.StreamHandler(TestStream())
    test_handler.formatter = logging.Formatter("[PYFLYBY] %(message)s")
    handler = pyflyby.logger.handlers[0]
    handler.emit = test_handler.emit



# Set $PYFLYBY_PATH to a predictable value.  For other env vars, set to defaults.
PYFLYBY_HOME = os.path.dirname(os.path.realpath(__file__))
os.environ["PYFLYBY_PATH"] = os.path.join(PYFLYBY_HOME, "etc/pyflyby")
os.environ["PYFLYBY_KNOWN_IMPORTS_PATH"] = ""
os.environ["PYFLYBY_MANDATORY_IMPORTS_PATH"] = ""
os.environ["PYFLYBY_LOG_LEVEL"] = ""
os.environ["PYTHONSTARTUP"] = ""

# Make sure that the virtualenv path is first.
os.environ["PATH"] = "%s:%s" % (os.path.dirname(sys.executable),
                                os.environ["PATH"])


# The following block is a workaround for IPython 0.11 and earlier versions.
# These versions of IPython get confused by sys.stdin not being a regular
# file at import time.
saved_sys_stdin = sys.stdin
try:
    sys.stdin = sys.__stdin__
    import IPython
    IPython # pyflakes
finally:
    sys.stdin = saved_sys_stdin
