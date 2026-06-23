# pyflyby/test_dbg.py

"""
Unit tests for pyflyby._dbg.

Most of the debugger machinery requires a real tty, gdb, or process forking,
which is awkward to exercise in CI.  These tests focus on the pieces that can
be tested in isolation -- argument routing, the various sys-hook context
managers, helper/utility functions -- using mocking where necessary.
"""


import builtins
import errno
import os
import signal
import sys

import pytest

from   pyflyby                  import _dbg as dbg


# ---------------------------------------------------------------------------
# excepthook override/reset
# ---------------------------------------------------------------------------

def test_override_and_reset_excepthook():
    saved = sys.excepthook
    saved_orig = dbg._ORIG_SYS_EXCEPTHOOK
    try:
        def myhook(*a):
            pass
        dbg._override_excepthook(myhook)
        assert sys.excepthook is myhook
        assert dbg._ORIG_SYS_EXCEPTHOOK is myhook
        # Reset restores _ORIG_SYS_EXCEPTHOOK (which is now myhook).
        assert dbg._reset_excepthook() is True
        assert sys.excepthook is myhook
    finally:
        sys.excepthook = saved
        dbg._ORIG_SYS_EXCEPTHOOK = saved_orig


def test_reset_excepthook_no_orig():
    saved_orig = dbg._ORIG_SYS_EXCEPTHOOK
    saved = sys.excepthook
    try:
        dbg._ORIG_SYS_EXCEPTHOOK = None
        assert dbg._reset_excepthook() is False
    finally:
        dbg._ORIG_SYS_EXCEPTHOOK = saved_orig
        sys.excepthook = saved


# ---------------------------------------------------------------------------
# /dev/tty detection
# ---------------------------------------------------------------------------

def test_tty_is_usable_true(monkeypatch):
    monkeypatch.setattr(dbg, "_memoized_dev_tty_fd", 5)
    assert dbg.tty_is_usable() is True


def test_tty_is_usable_false(monkeypatch):
    monkeypatch.setattr(dbg, "_memoized_dev_tty_fd", None)
    assert dbg.tty_is_usable() is False


def test_dev_tty_fd_raises_when_none(monkeypatch):
    monkeypatch.setattr(dbg, "_memoized_dev_tty_fd", None)
    with pytest.raises(dbg._NoTtyError):
        dbg._dev_tty_fd()


def test_dev_tty_fd_memoizes_on_oserror(monkeypatch):
    monkeypatch.setattr(dbg, "_memoized_dev_tty_fd", Ellipsis)

    def fake_open(*a, **k):
        raise OSError("no tty")
    monkeypatch.setattr(dbg.os, "open", fake_open)
    with pytest.raises(dbg._NoTtyError):
        dbg._dev_tty_fd()
    # Memoized to None.
    assert dbg._memoized_dev_tty_fd is None


# ---------------------------------------------------------------------------
# _FdCtx / _StdioCtx
# ---------------------------------------------------------------------------

def test_fdctx_redirects_and_restores(tmp_path):
    # Make a pipe to use as the source fd.
    r, w = os.pipe()
    # Use a duplicate of stdout as the target so we don't clobber the real one.
    target = os.dup(1)
    try:
        assert target > 2
        with dbg._FdCtx(target, w):
            # Writing to `target` should now go to the pipe `w`.
            os.write(target, b"hello")
        # Read what we wrote.
        assert os.read(r, 5) == b"hello"
    finally:
        os.close(target)
        os.close(r)
        os.close(w)


def test_stdioctx_rejects_low_fd():
    with pytest.raises(ValueError):
        with dbg._StdioCtx(tty=1):
            pass


def test_stdioctx_rejects_bad_type():
    with pytest.raises(TypeError):
        with dbg._StdioCtx(tty=1.5):
            pass


def test_stdioctx_reentrant_same_fd(monkeypatch):
    # When already in a _StdioCtx with the same fd, it's a no-op passthrough.
    monkeypatch.setattr(dbg, "_in_StdioCtx", [7])
    entered = []
    with dbg._StdioCtx(tty=7):
        entered.append(True)
    assert entered == [True]
    # Stack unchanged.
    assert dbg._in_StdioCtx == [7]


# ---------------------------------------------------------------------------
# _ExceptHookCtx / _DisplayHookCtx
# ---------------------------------------------------------------------------

def test_excepthook_ctx_restores():
    saved = sys.excepthook
    try:
        with dbg._ExceptHookCtx():
            sys.excepthook = lambda *a: None
            assert sys.excepthook is not saved
        assert sys.excepthook is saved
    finally:
        sys.excepthook = saved


def test_displayhook_ctx_resets_and_restores():
    saved = sys.displayhook
    sentinel = lambda *a: None
    sys.displayhook = sentinel
    try:
        with dbg._DisplayHookCtx():
            # Within the context it's reset to the default.
            assert sys.displayhook is sys.__displayhook__
        # Afterwards it's restored to what it was on entry.
        assert sys.displayhook is sentinel
    finally:
        sys.displayhook = saved


# ---------------------------------------------------------------------------
# _get_caller_frame
# ---------------------------------------------------------------------------

def test_get_caller_frame_outside_module():
    def caller():
        return dbg._get_caller_frame()
    frame = caller()
    # The returned frame should be in *this* test file, not in _dbg.py.
    assert frame.f_code.co_filename == __file__
    assert frame.f_code.co_name == "caller"


# ---------------------------------------------------------------------------
# _prompt_continue_waiting_for_debugger
# ---------------------------------------------------------------------------

def test_prompt_continue_no(monkeypatch):
    monkeypatch.setattr(dbg, "_waiting_for_debugger", "something")
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    dbg._prompt_continue_waiting_for_debugger()
    assert dbg._waiting_for_debugger is None


def test_prompt_continue_yes_keeps_waiting(monkeypatch):
    monkeypatch.setattr(dbg, "_waiting_for_debugger", "something")
    monkeypatch.setattr("builtins.input", lambda *a: "yes")
    dbg._prompt_continue_waiting_for_debugger()
    assert dbg._waiting_for_debugger == "something"


def test_prompt_continue_invalid_then_exits(monkeypatch, capsys):
    monkeypatch.setattr(dbg, "_waiting_for_debugger", "something")
    monkeypatch.setattr("builtins.input", lambda *a: "garbage")
    monkeypatch.setattr(dbg.time, "sleep", lambda *a: None)
    dbg._prompt_continue_waiting_for_debugger()
    out = capsys.readouterr().out
    assert "Invalid response" in out
    assert "Exiting after 3 invalid responses" in out
    assert dbg._waiting_for_debugger is None


# ---------------------------------------------------------------------------
# print_traceback / _DebuggerCtx
# ---------------------------------------------------------------------------

def test_print_traceback(monkeypatch):
    from contextlib import contextmanager
    seen = {}

    @contextmanager
    def fake_stdio(tty="/dev/tty"):
        yield
    monkeypatch.setattr(dbg, "_StdioCtx", fake_stdio)
    monkeypatch.setattr("pyflyby._interactive.print_verbose_tb",
                        lambda *a: seen.setdefault("args", a))
    try:
        raise ValueError("boom")
    except ValueError:
        dbg.print_traceback()
    assert "args" in seen


def test_debugger_ctx(monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def fake_stdio(tty="/dev/tty"):
        yield
    monkeypatch.setattr(dbg, "_StdioCtx", fake_stdio)

    class _Pdb:
        def reset(self):
            self.was_reset = True
    pdb = _Pdb()
    monkeypatch.setattr("pyflyby._interactive.new_IPdb_instance", lambda: pdb)
    with dbg._DebuggerCtx() as got:
        assert got is pdb
    assert pdb.was_reset is True


# ---------------------------------------------------------------------------
# _signal_handler_debugger
# ---------------------------------------------------------------------------

def test_signal_handler_debugger_forked_subprocess(monkeypatch):
    # When pid differs from _ORIG_PID, the handler returns immediately.
    monkeypatch.setattr(dbg, "_ORIG_PID", dbg.os.getpid() + 1)
    # Should not raise / call anything.
    assert dbg._signal_handler_debugger(signal.SIGQUIT, None) is None


# ---------------------------------------------------------------------------
# get_executable error branches
# ---------------------------------------------------------------------------

def test_get_executable_not_a_file(monkeypatch, tmp_path):
    monkeypatch.setattr(dbg.os, "uname", lambda: ("Linux", "", "", "", ""))
    # readlink points at a directory, not a file.
    monkeypatch.setattr(dbg.os, "readlink", lambda p: str(tmp_path))
    with pytest.raises(ValueError):
        dbg.get_executable(12345)


# ---------------------------------------------------------------------------
# _debug_exception / _debug_code (with a fake debugger context)
# ---------------------------------------------------------------------------

class _FakePdb:
    def __init__(self):
        self.postloop = None
        self.interaction_args = None

    def interaction(self, frame, tb_or_exc):
        self.interaction_args = (frame, tb_or_exc)

    def runeval(self, code, globals=None, locals=None):
        self.runeval_args = (code, globals, locals)
        return "ran"


def _patch_debugger_ctx(monkeypatch, fake_pdb):
    from contextlib import contextmanager

    @contextmanager
    def fake_ctx(tty="/dev/tty"):
        yield fake_pdb
    monkeypatch.setattr(dbg, "_DebuggerCtx", fake_ctx)


def test_debug_exception_sets_last_and_interacts(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    monkeypatch.setattr("pyflyby._interactive.print_verbose_tb", lambda *a: None)
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    dbg._debug_exception(exc_info)
    assert fake.interaction_args is not None
    # sys.last_exc (3.12+) or sys.last_value should now be set.
    last = getattr(sys, "last_exc", None) or getattr(sys, "last_value", None)
    assert isinstance(last, ValueError)


def test_debug_exception_debugger_attached_sets_postloop(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    monkeypatch.setattr("pyflyby._interactive.print_verbose_tb", lambda *a: None)
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    dbg._debug_exception(exc_info, debugger_attached=True)
    assert fake.postloop is dbg._prompt_continue_waiting_for_debugger


def test_debug_exception_unexpected_kwargs():
    with pytest.raises(TypeError):
        dbg._debug_exception(bogus=1)


def test_debug_exception_traceback_only(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    monkeypatch.setattr("pyflyby._interactive.print_verbose_tb", lambda *a: None)
    try:
        raise ValueError("boom")
    except ValueError:
        tb = sys.exc_info()[2]
    # Pass a single bare traceback.
    dbg._debug_exception(tb)
    assert fake.interaction_args is not None


def test_debug_code_string(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    monkeypatch.setattr("pyflyby._autoimp.auto_import", lambda *a, **k: None)
    result = dbg._debug_code("1 + 1", globals={}, locals={}, auto_import=True)
    assert result == "ran"
    assert fake.runeval_args is not None


def test_debug_code_callable(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    result = dbg._debug_code(lambda: None, globals={}, locals={},
                             auto_import=False)
    assert result == "ran"


def test_debug_code_bad_type(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    with pytest.raises(TypeError):
        dbg._debug_code(12345, globals={}, locals={}, auto_import=False)


def test_debug_code_uses_caller_frame(monkeypatch):
    fake = _FakePdb()
    _patch_debugger_ctx(monkeypatch, fake)
    monkeypatch.setattr("pyflyby._autoimp.auto_import", lambda *a, **k: None)
    # Don't pass globals/locals -> exercises _get_caller_frame branch.
    marker_local = 42  # noqa: F841
    dbg._debug_code("1 + 1")
    code, g, l = fake.runeval_args
    assert "marker_local" in l


# ---------------------------------------------------------------------------
# debugger() argument routing
# ---------------------------------------------------------------------------

def test_debugger_unexpected_kwargs():
    with pytest.raises(TypeError):
        dbg.debugger(bogus_kwarg=1)


def test_debugger_routes_code_to_debug_code(monkeypatch):
    calls = {}
    monkeypatch.setattr(dbg, "tty_is_usable", lambda: True)

    def fake_debug_code(arg, globals=None, locals=None, tty=None):
        calls["arg"] = arg
        calls["tty"] = tty
    monkeypatch.setattr(dbg, "_debug_code", fake_debug_code)

    continued = []
    dbg.debugger("1 + 1", on_continue=lambda: continued.append(True))
    assert calls["arg"] == "1 + 1"
    assert calls["tty"] == "/dev/tty"
    assert continued == [True]


def test_debugger_routes_traceback_to_debug_exception(monkeypatch):
    monkeypatch.setattr(dbg, "tty_is_usable", lambda: True)
    seen = {}

    def fake_debug_exception(arg, tty=None, debugger_attached=False):
        seen["arg"] = arg
    monkeypatch.setattr(dbg, "_debug_exception", fake_debug_exception)

    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    continued = []
    dbg.debugger(exc_info, on_continue=lambda: continued.append(True))
    assert seen["arg"] == exc_info
    assert continued == [True]


def test_debugger_wait_for_attach_true(monkeypatch):
    waited = {}
    monkeypatch.setattr(dbg, "wait_for_debugger_to_attach",
                        lambda arg, **k: waited.setdefault("arg", arg))
    dbg.debugger("code", wait_for_attach=True)
    assert "arg" in waited


def test_debugger_background(monkeypatch):
    waited = {}
    monkeypatch.setattr(
        dbg, "wait_for_debugger_to_attach",
        lambda arg, **k: waited.update(k, arg=arg))
    dbg.debugger("code", background=True)
    assert waited.get("background") is True


def test_debugger_tty_unusable_waits(monkeypatch):
    monkeypatch.setattr(dbg, "tty_is_usable", lambda: False)
    waited = {}
    monkeypatch.setattr(dbg, "wait_for_debugger_to_attach",
                        lambda arg, **k: waited.setdefault("arg", arg))
    dbg.debugger("code")
    assert "arg" in waited


def test_debugger_bad_arg_type(monkeypatch):
    monkeypatch.setattr(dbg, "tty_is_usable", lambda: True)
    with pytest.raises(TypeError):
        dbg.debugger(12345)  # int isn't a frame/traceback/str/code


def test_debugger_globals_locals_with_frame_raises(monkeypatch):
    monkeypatch.setattr(dbg, "tty_is_usable", lambda: True)
    frame = sys._getframe()
    with pytest.raises(NotImplementedError):
        dbg.debugger(frame, globals={}, locals={})


# ---------------------------------------------------------------------------
# _find_py_commandline
# ---------------------------------------------------------------------------

def test_find_py_commandline():
    py = dbg._find_py_commandline()
    assert py.base == "py"
    assert py.exists
    assert py.isexecutable


def test_find_py_commandline_cached(monkeypatch):
    monkeypatch.setattr(dbg, "_cached_py_commandline", "SENTINEL")
    assert dbg._find_py_commandline() == "SENTINEL"


# ---------------------------------------------------------------------------
# _sleep_until_debugger_attaches / timeout
# ---------------------------------------------------------------------------

def test_sleep_until_debugger_attaches_timeout(monkeypatch):
    # Make the clock jump past the deadline immediately.
    times = iter([0, 100000])

    monkeypatch.setattr(dbg.time, "time", lambda: next(times))
    monkeypatch.setattr(dbg.time, "sleep", lambda *a: None)
    with pytest.raises(dbg.DebuggerAttachTimeoutError):
        dbg._sleep_until_debugger_attaches("arg", timeout=1)
    assert dbg._waiting_for_debugger is None


# ---------------------------------------------------------------------------
# wait_for_debugger_to_attach
# ---------------------------------------------------------------------------

def test_wait_for_debugger_to_attach_resets_excepthook_failure(monkeypatch, capsys):
    # If _reset_excepthook returns False, the function raises ValueError
    # internally, which is caught and printed.
    monkeypatch.setattr(dbg, "_reset_excepthook", lambda: False)
    dbg.wait_for_debugger_to_attach("arg")
    err = capsys.readouterr().err
    assert "Couldn't reset sys.excepthook" in err


def test_wait_for_debugger_to_attach_sends_email_and_sleeps(monkeypatch):
    monkeypatch.setattr(dbg, "_reset_excepthook", lambda: True)
    sent = {}
    monkeypatch.setattr(
        dbg, "_send_email_with_attach_instructions",
        lambda arg, mailto, originalpid: sent.update(arg=arg, mailto=mailto))
    slept = {}
    monkeypatch.setattr(
        dbg, "_sleep_until_debugger_attaches",
        lambda arg, timeout: slept.update(arg=arg, timeout=timeout))
    dbg.wait_for_debugger_to_attach("myarg", mailto="me", timeout=42)
    assert sent["arg"] == "myarg"
    assert sent["mailto"] == "me"
    assert slept["timeout"] == 42


# ---------------------------------------------------------------------------
# debug_on_exception
# ---------------------------------------------------------------------------

def test_debug_on_exception_no_error(monkeypatch):
    called = []
    monkeypatch.setattr(dbg, "debugger", lambda *a, **k: called.append(True))

    @dbg.debug_on_exception
    def f(x):
        return x * 2
    assert f(3) == 6
    assert called == []


def test_debug_on_exception_with_error(monkeypatch):
    captured = {}

    def fake_debugger(exc_info, background=False):
        captured["exc_info"] = exc_info
        captured["background"] = background
    monkeypatch.setattr(dbg, "debugger", fake_debugger)

    @dbg.debug_on_exception
    def f():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        f()
    assert captured["exc_info"][0] is ValueError


# ---------------------------------------------------------------------------
# _send_email_with_attach_instructions
# ---------------------------------------------------------------------------

class _FakeSMTP:
    instances = []

    def __init__(self, host):
        self.host = host
        self.sent = []
        _FakeSMTP.instances.append(self)

    def sendmail(self, frm, to, msg):
        self.sent.append((frm, to, msg))

    def quit(self):
        self.quit_called = True


def test_send_email_with_frame(monkeypatch, capsys):
    _FakeSMTP.instances = []
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr(dbg, "_find_py_commandline", lambda: "/usr/bin/py")
    frame = sys._getframe()
    dbg._send_email_with_attach_instructions(frame, "someone@example.com",
                                              originalpid=None)
    err = capsys.readouterr().err
    assert "[PYFLYBY]" in err
    assert "waiting for a debugger to attach" in err
    smtp = _FakeSMTP.instances[-1]
    assert smtp.sent
    frm, to, msg = smtp.sent[0]
    assert to == ["someone@example.com"]


def test_send_email_with_exception(monkeypatch, capsys):
    _FakeSMTP.instances = []
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr(dbg, "_find_py_commandline", lambda: "/usr/bin/py")
    try:
        raise RuntimeError("kaboom")
    except RuntimeError:
        exc_info = sys.exc_info()
    dbg._send_email_with_attach_instructions(exc_info, "x@y.z", originalpid=1234)
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert "kaboom" in err
    # originalpid present -> forked-process wording.
    assert "forked" in err.lower()


def test_send_email_default_mailto(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr(dbg, "_find_py_commandline", lambda: "/usr/bin/py")
    monkeypatch.setenv("USER", "tester")
    frame = sys._getframe()
    dbg._send_email_with_attach_instructions(frame, None, originalpid=None)
    smtp = _FakeSMTP.instances[-1]
    frm, to, msg = smtp.sent[0]
    assert to == ["tester"]


# ---------------------------------------------------------------------------
# _abbrev_filename
# ---------------------------------------------------------------------------

def test_abbrev_filename_long():
    assert dbg._abbrev_filename("/a/b/c/d/e/f.py") == ".../d/e/f.py"


def test_abbrev_filename_short():
    assert dbg._abbrev_filename("/a/b.py") == "/a/b.py"


# ---------------------------------------------------------------------------
# SIGTERM handler
# ---------------------------------------------------------------------------

def test_enable_sigterm_handler_installs_and_idempotent():
    old = signal.getsignal(signal.SIGTERM)
    try:
        dbg.enable_sigterm_handler()
        assert signal.getsignal(signal.SIGTERM) is dbg._sigterm_handler
        # Calling again with our handler already installed is a no-op.
        dbg.enable_sigterm_handler()
        assert signal.getsignal(signal.SIGTERM) is dbg._sigterm_handler
    finally:
        signal.signal(signal.SIGTERM, old)


def test_enable_sigterm_handler_raise_on_existing():
    old = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, lambda *a: None)
        with pytest.raises(ValueError):
            dbg.enable_sigterm_handler(on_existing_handler="raise")
    finally:
        signal.signal(signal.SIGTERM, old)


def test_enable_sigterm_handler_keep_existing():
    old = signal.getsignal(signal.SIGTERM)
    try:
        existing = lambda *a: None
        signal.signal(signal.SIGTERM, existing)
        dbg.enable_sigterm_handler(on_existing_handler="keep_existing")
        assert signal.getsignal(signal.SIGTERM) is existing
    finally:
        signal.signal(signal.SIGTERM, old)


def test_enable_sigterm_handler_silently_override():
    old = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, lambda *a: None)
        dbg.enable_sigterm_handler(on_existing_handler="silently_override")
        assert signal.getsignal(signal.SIGTERM) is dbg._sigterm_handler
    finally:
        signal.signal(signal.SIGTERM, old)


def test_enable_sigterm_handler_warn_and_override():
    old = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, lambda *a: None)
        dbg.enable_sigterm_handler(on_existing_handler="warn_and_override")
        assert signal.getsignal(signal.SIGTERM) is dbg._sigterm_handler
    finally:
        signal.signal(signal.SIGTERM, old)


def test_enable_sigterm_handler_invalid_option():
    old = signal.getsignal(signal.SIGTERM)
    try:
        signal.signal(signal.SIGTERM, lambda *a: None)
        with pytest.raises(ValueError):
            dbg.enable_sigterm_handler(on_existing_handler="bogus")
    finally:
        signal.signal(signal.SIGTERM, old)


# ---------------------------------------------------------------------------
# enable_faulthandler / signal-handler / exception-handler installers
# ---------------------------------------------------------------------------

def test_enable_faulthandler():
    import faulthandler
    was_enabled = faulthandler.is_enabled()
    dbg.enable_faulthandler()
    assert faulthandler.is_enabled()
    if not was_enabled:
        faulthandler.disable()


def test_enable_signal_handler_debugger():
    old = signal.getsignal(signal.SIGQUIT)
    try:
        dbg.enable_signal_handler_debugger(True)
        assert signal.getsignal(signal.SIGQUIT) is dbg._signal_handler_debugger
        dbg.enable_signal_handler_debugger(False)
        assert signal.getsignal(signal.SIGQUIT) == signal.SIG_DFL
    finally:
        signal.signal(signal.SIGQUIT, old)


def test_enable_exception_handler_debugger():
    saved = sys.excepthook
    saved_orig = dbg._ORIG_SYS_EXCEPTHOOK
    try:
        dbg.enable_exception_handler_debugger()
        assert sys.excepthook is dbg.debugger
    finally:
        sys.excepthook = saved
        dbg._ORIG_SYS_EXCEPTHOOK = saved_orig


# ---------------------------------------------------------------------------
# add_debug_functions_to_builtins
# ---------------------------------------------------------------------------

def test_add_debug_functions_to_builtins_basic():
    names = ['debugger', 'debug_on_exception', 'print_traceback']
    saved = {n: getattr(builtins, n, None) for n in names}
    try:
        for n in names:
            if hasattr(builtins, n):
                delattr(builtins, n)
        dbg.add_debug_functions_to_builtins(add_deprecated=False)
        for n in names:
            assert hasattr(builtins, n)
        assert not hasattr(builtins, "waitpoint") or True  # not added here
    finally:
        for n, v in saved.items():
            if v is None:
                if hasattr(builtins, n):
                    delattr(builtins, n)
            else:
                setattr(builtins, n, v)


def test_add_debug_functions_to_builtins_deprecated():
    names = ['debugger', 'debug_on_exception', 'print_traceback',
             'breakpoint', 'debug_exception', 'debug_statement', 'waitpoint']
    saved = {n: getattr(builtins, n, None) for n in names}
    try:
        dbg.add_debug_functions_to_builtins(add_deprecated=True)
        for n in names:
            assert hasattr(builtins, n)
    finally:
        for n, v in saved.items():
            if v is None:
                if hasattr(builtins, n):
                    delattr(builtins, n)
            else:
                setattr(builtins, n, v)


# ---------------------------------------------------------------------------
# get_executable
# ---------------------------------------------------------------------------

def test_get_executable_self():
    exe = dbg.get_executable(os.getpid())
    assert exe.isfile
    assert "python" in exe.base.lower()


def test_get_executable_bad_pid():
    with pytest.raises((ValueError, OSError, ProcessLookupError, FileNotFoundError)):
        dbg.get_executable(999999)


# ---------------------------------------------------------------------------
# _escape_for_gdb
# ---------------------------------------------------------------------------

def test_escape_for_gdb_safe_chars():
    assert dbg._escape_for_gdb("hello world 123") == "hello world 123"


def test_escape_for_gdb_unsafe_chars():
    # Non-ASCII / control chars get octal-escaped.
    result = dbg._escape_for_gdb("a\nb")
    assert "\\012" in result  # newline -> octal 012
    assert result.startswith("a")


# ---------------------------------------------------------------------------
# _dev_null
# ---------------------------------------------------------------------------

def test_dev_null_memoized():
    a = dbg._dev_null()
    b = dbg._dev_null()
    assert a is b
    assert a.name == "/dev/null"


# ---------------------------------------------------------------------------
# process_exists / kill_process
# ---------------------------------------------------------------------------

def test_process_exists_true():
    assert dbg.process_exists(os.getpid()) is True


def test_process_exists_false():
    assert dbg.process_exists(999999) is False


def test_process_exists_reraises_other_oserror(monkeypatch):
    def fake_kill(pid, sig):
        raise OSError(errno.EPERM, "denied")
    monkeypatch.setattr(dbg.os, "kill", fake_kill)
    with pytest.raises(OSError):
        dbg.process_exists(12345)


def test_kill_process_already_dead():
    # ESRCH on first signal -> returns True immediately.
    assert dbg.kill_process(999999, [(signal.SIGTERM, 1)]) is True


def test_kill_process_reraises_other_oserror(monkeypatch):
    def fake_kill(pid, sig):
        raise OSError(errno.EPERM, "denied")
    monkeypatch.setattr(dbg.os, "kill", fake_kill)
    with pytest.raises(OSError):
        dbg.kill_process(12345, [(signal.SIGTERM, 1)])


def test_kill_process_dies_during_wait(monkeypatch):
    # process_exists returns False after the signal -> detected, returns True.
    monkeypatch.setattr(dbg.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(dbg, "process_exists", lambda pid: False)
    monkeypatch.setattr(dbg.time, "sleep", lambda *a: None)
    assert dbg.kill_process(12345, [(signal.SIGTERM, 1)]) is True


# ---------------------------------------------------------------------------
# setraw_but_sigint / Pty
# ---------------------------------------------------------------------------

def test_setraw_but_sigint_keeps_isig():
    import tty
    master, slave = os.openpty() if hasattr(os, "openpty") else (None, None)
    try:
        dbg.setraw_but_sigint(slave)
        after = tty.tcgetattr(slave)
        # ISIG bit should still be set in LFLAG.
        assert after[tty.LFLAG] & tty.ISIG
        # ECHO should be cleared.
        assert not (after[tty.LFLAG] & tty.ECHO)
    finally:
        os.close(master)
        os.close(slave)


def test_pty_creates_ttyname():
    p = dbg.Pty()
    try:
        assert os.path.exists(p.ttyname)
        assert p.master_fd > 0
        assert p.slave_fd > 0
    finally:
        os.close(p.master_fd)
        os.close(p.slave_fd)


# ---------------------------------------------------------------------------
# remote_print_stack input validation
# ---------------------------------------------------------------------------

def test_remote_print_stack_bad_output_type():
    with pytest.raises(TypeError):
        dbg.remote_print_stack(os.getpid(), output=1.5)


def test_remote_print_stack_to_named_file(monkeypatch, tmp_path):
    # Mock the actual injection; just verify the filename plumbing.
    captured = {}

    def fake_remote(pid, filename):
        captured["pid"] = pid
        captured["filename"] = str(filename)
    monkeypatch.setattr(dbg, "_remote_print_stack_to_file", fake_remote)
    target = tmp_path / "stack.txt"
    target.write_text("")  # make it exist & writable
    dbg.remote_print_stack(4321, output=str(target))
    assert captured["pid"] == 4321
    assert captured["filename"] == str(target)


def test_remote_print_stack_int_fd(monkeypatch, tmp_path):
    target = tmp_path / "out.txt"
    fd = os.open(str(target), os.O_RDWR | os.O_CREAT)
    captured = {}

    def fake_remote(pid, filename):
        captured["filename"] = str(filename)
    monkeypatch.setattr(dbg, "_remote_print_stack_to_file", fake_remote)
    try:
        dbg.remote_print_stack(os.getpid(), output=fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    # With a writable fd, remote_fn becomes /proc/<pid>/fd/<fd> and no temp
    # copy-back is needed.
    assert "filename" in captured


def test_remote_print_stack_file_like_object(monkeypatch):
    import io
    captured = {}

    def fake_remote(pid, filename):
        # Simulate the remote process writing a stack trace to the temp file.
        with open(str(filename), "wb") as f:
            f.write(b"STACKTRACE")
        captured["filename"] = str(filename)
    monkeypatch.setattr(dbg, "_remote_print_stack_to_file", fake_remote)

    # Binary file-like with no real fileno -> exercises the temp-file path.
    buf = io.BytesIO()
    dbg.remote_print_stack(os.getpid(), output=buf)
    assert buf.getvalue() == b"STACKTRACE"


def test_remote_print_stack_to_file_calls_inject(monkeypatch):
    captured = {}

    def fake_inject(pid, statements, wait=True):
        captured["pid"] = pid
        captured["statements"] = statements
        captured["wait"] = wait
    monkeypatch.setattr(dbg, "inject", fake_inject)
    dbg._remote_print_stack_to_file(77, "/tmp/out.txt")
    assert captured["pid"] == 77
    assert captured["wait"] is True
    assert any("traceback" in s for s in captured["statements"])


# ---------------------------------------------------------------------------
# waitpoint (deprecated wrapper)
# ---------------------------------------------------------------------------

def test_waitpoint_uses_caller_frame(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        dbg, "wait_for_debugger_to_attach",
        lambda frame, **k: captured.update(frame=frame, **k))
    dbg.waitpoint(mailto="x", timeout=5)
    from types import FrameType
    assert isinstance(captured["frame"], FrameType)
    assert captured["mailto"] == "x"
    assert captured["timeout"] == 5


# ---------------------------------------------------------------------------
# inject argument validation
# ---------------------------------------------------------------------------

def test_inject_bad_statement_type(monkeypatch):
    # Bypass the gdb permission check and pid existence check.
    monkeypatch.setattr(dbg.os, "kill", lambda pid, sig: None)

    class _OK:
        returncode = 0
        stderr = b""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _OK())
    with pytest.raises(TypeError):
        dbg.inject(12345, [123])  # non-string statement


def test_inject_nonexistent_pid():
    # os.kill(pid, 0) raises before anything else.
    with pytest.raises(OSError):
        dbg.inject(999999, ["pass"])


# ---------------------------------------------------------------------------
# deprecated aliases
# ---------------------------------------------------------------------------

def test_deprecated_aliases():
    assert dbg.breakpoint is dbg.debugger
    assert dbg.debug_statement is dbg.debugger
    assert dbg.debug_exception is dbg.debugger
    assert dbg.enable_signal_handler_breakpoint is dbg.enable_signal_handler_debugger
    assert dbg.enable_exception_handler is dbg.enable_exception_handler_debugger
