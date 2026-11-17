# pyflyby/tests/_test_utils.py
"""
Test-only helpers shared across the pyflyby test suite.
"""


from   contextlib               import contextmanager
import os
import pytest
import sys


@contextmanager
def EnvVarCtx(**kwargs):
    """
    Context manager that temporarily modifies os.environ.
    """
    unset = object()
    old = {}
    try:
        for k, v in kwargs.items():
            old[k] = os.environ.get(k, unset)
            os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is unset:
                del os.environ[k]
            else:
                os.environ[k] = v


# pexpect/ptyprocess call os.forkpty(); Python 3.15 turns the resulting
# DeprecationWarning into an error. Which I expect it to be fixed by a newer
# pexpect/ptyprocess release , at which point this strict xfail will start failing
# and can be removed.
xfail_forkpty_py315 = pytest.mark.xfail(
    sys.version_info >= (3, 15),
    reason="pexpect/ptyprocess forkpty() DeprecationWarning on Python 3.15",
    raises=DeprecationWarning,
    strict=True,
)
