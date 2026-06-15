


import os
import pytest
import re
import sys


_already_ran_setup = False

def pytest_runtest_setup(item):
    """
    Run the logger setup once.
    """
    # Although we only bother doing this once (and never tearDown), we still
    # do this in a pytest_runtest_setup, rather than e.g. pytest_configure()
    # because otherwise py.test can get confused by having already loaded
    # pyflyby from a different location.
    global _already_ran_setup
    if _already_ran_setup:
        return
    _already_ran_setup = True
    _setup_logger()


def pytest_assertrepr_compare(config, op, left, right):
    """
    Provide a rich, line-by-line diff when an ``assert a == b`` of two
    ``PythonBlock`` objects fails, instead of pytest's opaque
    ``<PythonBlock ...> == <PythonBlock ...>``.
    """
    if op != "==":
        return None
    from pyflyby._parse import PythonBlock
    if not (isinstance(left, PythonBlock) and isinstance(right, PythonBlock)):
        return None
    import difflib
    lines = ["PythonBlock(left) == PythonBlock(right) failed:"]
    left_lines = str(left).splitlines()
    right_lines = str(right).splitlines()
    if left_lines != right_lines:
        lines.append("  text differs (- left, + right):")
        diff = difflib.unified_diff(
            left_lines, right_lines, lineterm="",
            fromfile="left", tofile="right")
        lines.extend("  " + line for line in diff)
    if left.flags != right.flags:
        lines.append("  flags differ:")
        lines.append("    left:  %s" % (left.flags,))
        lines.append("    right: %s" % (right.flags,))
    return lines


def pytest_report_header(config):
    import IPython
    print("IPython %s" % (IPython.__version__))
    import pyflyby
    dir = os.path.dirname(pyflyby.__file__)
    print("pyflyby %s from %s" % (pyflyby.__version__, dir))

if getattr(pytest, 'version_tuple', (0,0))[:2] >= (7, 0):
    def pytest_load_initial_conftests(early_config, parser, args):
        args[:] = ["--no-success-flaky-report", "--no-flaky-report"] + args
else:
    def pytest_cmdline_preparse(config, args):
        args[:] = ["--no-success-flaky-report", "--no-flaky-report"] + args

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
os.environ["PYFLYBY_LOG_LEVEL"] = ""
os.environ["PYTHONSTARTUP"] = ""

# Make sure that the virtualenv path is first.
os.environ["PATH"] = "%s:%s" % (os.path.dirname(sys.executable),
                                os.environ["PATH"])

# Unload any already-imported pyflyby.  This could happen if the user's
# usercustomize imported pyflyby.  That would probably be the "production"
# pyflyby rather than the one being developed & tested.
for k in list(sys.modules.keys()):
    if k == "pyflyby" or k.startswith("pyflyby."):
        del sys.modules[k]

# Make sure we import pyflyby from this repository, as opposed to any other
# copy of pyflyby.  This does prevent us from testing using the test cases of
# one repository against the modules from another repository.  But that's not
# a common case; better to avoid confusion in the more common case between
# production vs development pyflyby.
pylib = os.path.join(PYFLYBY_HOME, "lib/python")
sys.path.insert(0, pylib)
os.environ["PYTHONPATH"] = ":".join(
    [pylib] + list(filter(None, os.environ.get("PYTHONPATH", "").split(":"))))
import pyflyby

fn = re.sub("[.]py[co]$", ".py", pyflyby.__file__)
expected_fn = os.path.join(PYFLYBY_HOME, "lib/python/pyflyby/__init__.py")
assert fn == expected_fn, "pyflyby got loaded from %s; expected %s" % (fn, expected_fn)


