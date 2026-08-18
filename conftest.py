


import os
import pytest
import re
import sys
from   textwrap                 import dedent


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

def _capture_logger(caplog, name):
    """
    Capture records of the named logger via caplog.

    Temporarily replace the logger's handlers with caplog's handler: records
    become assertable via ``caplog.messages`` / ``caplog.records``, and log
    output stays out of stdout/stderr so capsys sees only genuine program
    output.  Propagation is disabled for the duration: caplog's handler is
    also attached to the root logger, so a propagating record would be
    captured twice.
    """
    import logging
    logger = logging.getLogger(name)
    saved_handlers = logger.handlers[:]
    saved_propagate = logger.propagate
    logger.handlers[:] = [caplog.handler]
    logger.propagate = False
    try:
        yield caplog
    finally:
        logger.handlers[:] = saved_handlers
        logger.propagate = saved_propagate


@pytest.fixture
def tmp_module(tmp_path):
    """
    Factory writing importable modules under a temp dir on ``sys.path``.

    Call as ``tmp_module(name, source)``; returns the name.  Everything is
    unwound afterwards: sys.modules, ModuleHandle's interned instance (which
    caches ``exports``/``runtime_exports``), and import_module's memo -- that
    last one is keyed on the module name alone, so without clearing it a later
    test reusing a name would silently get this module back.
    """
    names = []

    def make(name, source, package=False):
        if package:
            (tmp_path / name).mkdir(exist_ok=True)
            (tmp_path / name / "__init__.py").write_text(dedent(source))
        else:
            (tmp_path / (name + ".py")).write_text(dedent(source))
        names.append(name)
        return name

    make.path = tmp_path
    sys.path.insert(0, str(tmp_path))
    try:
        yield make
    finally:
        sys.path.remove(str(tmp_path))
        for name in names:
            for mod in [m for m in sys.modules
                        if m == name or m.startswith(name + ".")]:
                del sys.modules[mod]
            ModuleHandle._cls_cache.pop(DottedIdentifier(name), None)
        import_module.cache_clear()


# A module whose __all__ is built at run time, as numpy's is: static parsing
# can't evaluate it, so only runtime_exports sees alpha and beta.
DYNAMIC_ALL_SOURCE = """
    _names = ["alpha", "beta"]
    for _n in _names:
        globals()[_n] = _n
    __all__ = list(_names)
"""


@pytest.fixture
def dynamic_all_module(tmp_module):
    """Name of an importable module with a run-time-built ``__all__``."""
    return tmp_module("pyflyby_test_dynamic_all_49172056", DYNAMIC_ALL_SOURCE)


@pytest.fixture
def pyflyby_log(caplog):
    yield from _capture_logger(caplog, "pyflyby")


@pytest.fixture
def saveframe_log(caplog):
    yield from _capture_logger(caplog, "pyflyby._saveframe")


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

# Imported here rather than at the top of the file: pyflyby must not be
# imported until sys.path has been fixed up just above.
from pyflyby._idents import DottedIdentifier  # noqa: E402
from pyflyby._modules import ModuleHandle, import_module  # noqa: E402
