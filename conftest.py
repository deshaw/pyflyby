

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
    handler = pyflyby.logger.handlers[0]
    handler.stream = TestStream()
    handler.formatter = logging.Formatter("[PYFLYBY] %(message)s")
