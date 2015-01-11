# pyflyby/_dbg.py.
# Copyright (C) 2009, 2010, 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

# TODO: wrap names in single global name e.g. DEBUGGER

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import contextlib
from   contextlib               import contextmanager
import errno
from   functools                import wraps
import os
import pwd
import signal
import sys
import time

from   pyflyby._file            import Filename


_waiting_for_breakpoint = False


class _NoTtyError(Exception):
    pass


_memoized_dev_tty_fd = Ellipsis
def _dev_tty_fd():
    """
    Return a file descriptor opened to /dev/tty.
    Memoized.
    """
    global _memoized_dev_tty_fd
    if _memoized_dev_tty_fd is Ellipsis:
        try:
            _memoized_dev_tty_fd = os.open("/dev/tty", os.O_RDWR)
        except OSError:
            _memoized_dev_tty_fd = None
    if _memoized_dev_tty_fd is None:
        raise _NoTtyError
    return _memoized_dev_tty_fd


@contextmanager
def _FdCtx(target_fd, src_fd):
    assert target_fd != src_fd
    saved_fd = os.dup(target_fd)
    assert saved_fd > 2, "saved_fd == %d" % (saved_fd,)
    assert saved_fd != target_fd and saved_fd != src_fd
    os.dup2(src_fd, target_fd)
    try:
        yield
    finally:
        os.dup2(saved_fd, target_fd)


_in_StdioCtx = []

@contextmanager
def _StdioCtx(tty="/dev/tty"):
    '''
    Within the context, force fd {0, 1, 2}, sys.__{stdin,stdout,stderr}__,
    sys.{stdin,stdout,stderr} to fd.  This allows us to use the debugger even
    if stdio is otherwise redirected.

    @type tty:
      C{int} or C{str}
    @param tty:
      Tty to use.  Either a file descriptor or a name of a tty.
    '''
    from ._interactive import UpdateIPythonStdioCtx
    to_close = None
    if isinstance(tty, int):
        fd = tty
    elif isinstance(tty, str):
        if tty == "/dev/tty":
            fd = _dev_tty_fd()
        else:
            fd = os.open(tty, os.O_RDWR)
            to_close = fd
    else:
        raise TypeError("_StdioCtx(): tty should be an int or str")
    if _in_StdioCtx and _in_StdioCtx[-1] == fd:
        # Same context; do nothing.
        assert to_close is None
        yield
        return
    if not fd > 2:
        raise ValueError("_StdioCtx: unsafe to use fd<=2; fd==%d" % (fd,))
    _in_StdioCtx.append(fd)
    saved_stdin    = sys.stdin
    saved_stdin__  = sys.__stdin__
    saved_stdout   = sys.stdout
    saved_stdout__ = sys.__stdout__
    saved_stderr   = sys.stderr
    saved_stderr__ = sys.__stderr__
    try:
        sys.stdout.flush(); sys.__stdout__.flush()
        sys.stderr.flush(); sys.__stderr__.flush()
        with contextlib.nested(_FdCtx(0, fd), _FdCtx(1, fd), _FdCtx(2, fd)):
            with contextlib.nested(
                    os.fdopen(0, 'r'),
                    os.fdopen(1, 'w'),
                    os.fdopen(2, 'w', 1)) as (fd0, fd1, fd2):
                sys.stdin  = sys.__stdin__  = fd0
                sys.stdout = sys.__stdout__ = fd1
                sys.stderr = sys.__stderr__ = fd2
                # Update IPython's stdin/stdout/stderr temporarily.
                with UpdateIPythonStdioCtx():
                    yield
    finally:
        assert _in_StdioCtx and _in_StdioCtx[-1] == fd
        _in_StdioCtx.pop(-1)
        sys.stdin      = saved_stdin
        sys.__stdin__  = saved_stdin__
        sys.stdout     = saved_stdout
        sys.__stdout__ = saved_stdout__
        sys.stderr     = saved_stderr
        sys.__stderr__ = saved_stderr__
        if to_close is not None:
            try:
                os.close(to_close)
            except (OSError, IOError):
                pass


@contextmanager
def _ExceptHookCtx():
    '''
    Context manager that restores C{sys.excepthook} upon exit.
    '''
    saved_excepthook = sys.excepthook
    try:
        # TODO: should we set sys.excepthook = sys.__excepthook__ ?
        yield
    finally:
        sys.excepthook = saved_excepthook


@contextmanager
def _DisplayHookCtx():
    '''
    Context manager that resets C{sys.displayhook} to the default value upon
    entry, and restores the pre-context value upon exit.
    '''
    saved_displayhook = sys.displayhook
    try:
        sys.displayhook = sys.__displayhook__
        yield
    finally:
        sys.displayhook = saved_displayhook


def print_traceback(*exc_info):
    """
    Print a traceback, using IPython's ultraTB if possible.

    Output goes to /dev/tty.

    @param exc_info:
      3 arguments as returned by sys.exc_info().
    """
    from pyflyby._interactive import print_verbose_tb
    if not exc_info:
        exc_info = sys.exc_info()
    with _StdioCtx():
        print_verbose_tb(*exc_info)


@contextmanager
def _DebuggerCtx(tty="/dev/tty"):
    """
    A context manager that sets up the environment (stdio, sys hooks) for a
    debugger, initializes IPython if necessary, and creates a debugger instance.

    @return:
      Context manager that yields a Pdb instance.
    """
    from pyflyby._interactive import new_IPdb_instance
    with _StdioCtx(tty):
        with _ExceptHookCtx():
            with _DisplayHookCtx():
                pdb = new_IPdb_instance()
                pdb.reset()
                yield pdb


def _get_caller_frame():
    '''
    Get the closest frame from outside this module.

    @rtype:
      C{FrameType}
    '''
    this_filename = _get_caller_frame.func_code.co_filename
    f = sys._getframe()
    while (f.f_back and (
            f.f_code.co_filename == this_filename or
            (f.f_back.f_back and
             f.f_code.co_filename == "<string>" and
             f.f_code.co_name == "<module>" and
             f.f_back.f_code.co_filename == this_filename))):
        f = f.f_back
    if f.f_code.co_filename == "<string>" and f.f_code.co_name == "<module>":
        # Skip an extra string eval frame for attaching a debugger.
        # TODO: pass in a frame or maximum number of string frames to skip.
        # We shouldn't skip "<string>" if it comes from regular user code.
        f = f.f_back
    return f


def debug_exception(*exc_info):
    """
    Debug an exception -- print a stack trace and enter the debugger.

    Suitable to be assigned to sys.excepthook.
    """
    if not exc_info:
        exc_info = sys.exc_info()
    with _DebuggerCtx() as pdb:
        print_traceback(*exc_info)
        pdb.interaction(None, exc_info[2])


def debug_statement(statement, globals=None, locals=None, auto_import=True):
    """
    Run code under the debugger.

    @type statement:
      C{str}, C{PythonBlock}
    """
    if globals is None or locals is None:
        caller_frame = _get_caller_frame()
        if globals is None:
            globals = caller_frame.f_globals
        if locals is None:
            locals = caller_frame.f_locals
        del caller_frame
    with _DebuggerCtx() as pdb:
        print("Entering debugger.  Use 'n' to step, 'c' to run, 'q' to stop.")
        print("")
        from ._parse import PythonBlock
        # Compile the block so that we can get the right compile mode.
        block = PythonBlock(statement)
        # TODO: enter text into linecache
        code = block.compile()
        if auto_import:
            from ._autoimp import auto_import as auto_import_f
            auto_import_f(block, [globals, locals])
        return pdb.runeval(code, globals=globals, locals=locals)


def breakpoint(tty="/dev/tty", frame=None, on_continue=lambda: None):
    '''
    Break into debugger - similar to 'import pdb; pdb.set_trace()'.
    Suitable to be called from scripts and signal handlers.

    @param frame:
      Frame to debug.  If C{None}, use non-dbg caller.
    @param on_continue:
      Function to call upon continuing.
    '''
    global _waiting_for_breakpoint
    _waiting_for_breakpoint = False
    if frame is None:
        frame = _get_caller_frame()
    pdb_context = _DebuggerCtx(tty)
    pdb = pdb_context.__enter__()
    print("Entering debugger.  Use 'n' to step, 'c' to continue running, 'q' to quit Python completely.")
    def set_continue():
        pdb.stopframe = pdb.botframe
        pdb.returnframe = None
        sys.settrace(None)
        print("Continuing execution.")
        pdb_context.__exit__(None, None, None)
        on_continue()
    def set_quit():
        raise SystemExit("Quitting as requested while debugging.")
    pdb.set_continue = set_continue
    pdb.set_quit = set_quit
    pdb.do_EOF = pdb.do_continue
    pdb.set_trace(frame)
    # Note: set_trace() installs a tracer and returns; that means we can't use
    # context managers around set_trace(): the __exit__() would be called
    # right away, not after continuing/quitting.


_cached_py_commandline = None
def _find_py_commandline():
    global _cached_py_commandline
    if _cached_py_commandline is not None:
        return _cached_py_commandline
    import pyflyby
    pkg_path = Filename(pyflyby.__path__[0])
    assert pkg_path.base == "pyflyby"
    d = pkg_path.dir
    if d.base == "bin":
        # Running from source tree
        bindir = d
    else:
        # Installed by setup.py
        while d.dir != d:
            d = d.dir
            bindir = d / "bin"
            if bindir.exists:
                break
        else:
            raise ValueError(
                "Couldn't find 'py' script: "
                "couldn't find 'bin' dir from package path %s" % (pkg_path,))
    candidate = bindir / "py"
    if not candidate.exists:
        raise ValueError(
            "Couldn't find 'py' script: expected it at %s" % (candidate,))
    if not candidate.isexecutable:
        raise ValueError(
            "Found 'py' script at %s but it's not executable" % (candidate,))
    _cached_py_commandline = candidate
    return candidate


def get_hostname():
    import socket
    return socket.gethostbyaddr(socket.gethostname())[0]



class DebuggerAttachTimeoutError(Exception):
    pass


def wait_for_debugger_attach(timeout=86400):
    deadline = time.time() + timeout
    global _waiting_for_breakpoint
    _waiting_for_breakpoint = True
    while _waiting_for_breakpoint:
        if time.time() > deadline:
            raise DebuggerAttachTimeoutError
        time.sleep(0.5)


# TODO: expose as parameter to breakpoint()?
def waitpoint(frame=None, mailto=None, background=False, timeout=86400):
    """
    Send email to user and wait for debugger to attach.

    @param frame:
      Frame to debug.  If C{None}, use non-dbg caller.
    @param mailto:
      Recipient to email.  Defaults to $USER or current user.
    @param background:
      If True, fork a child process and continue in parent.
    @param timeout:
      Maximum number of seconds to wait for user to attach debugger.
    """
    if background:
        originalpid = os.getpid()
        if os.fork() != 0:
            return
    else:
        originalpid = None
    try:
        # Send email.
        _send_email_about_waitpoint(frame, mailto, originalpid=originalpid)
        # Wait for debugger to attach.
        wait_for_debugger_attach(timeout=timeout)
    except:
        if not background:
            raise
        # Swallow all exceptions here (although we don't expect any).  The
        # parent process already continued; we don't want to double any
        # actions.  TODO: log to a log file?
        pass
    if background:
        # Exit.  Note that the original process already continued.
        os._exit(1)




def debug_on_exception(function):
    """
    Decorator that wraps a function so that we enter a debugger upon exception.
    """
    @wraps(function)
    def wrapped_function(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            # TODO: use waitpoint if no /dev/tty
            debug_exception()
            raise
    return wrapped_function




def _send_email_about_waitpoint(frame, mailto, originalpid):
    from   email.mime.text import MIMEText
    import smtplib
    import traceback
    if frame is None:
        frame = _get_caller_frame()
    user = pwd.getpwuid(os.geteuid()).pw_name
    if mailto is None:
        mailto = user
    hostname = get_hostname()
    py = _find_py_commandline()
    pid = os.getpid()
    argv = ' '.join(sys.argv)
    tb = ''.join("    %s" % (line,) for line in traceback.format_stack(frame))
    d = dict(
        filename    =frame.f_code.co_filename,
        line        =frame.f_lineno,
        hostname    =hostname,
        username    =user,
        py          =py,
        originalpid =originalpid,
        pid         =pid,
        argv        =argv,
        argv_abbrev =argv[:40],
        traceback   =tb,
        )
    if originalpid is None:
        email_body = """\
While running {argv_abbrev}, waitpoint reached at {filename}:{line}

Please run:
    ssh -t {hostname} {py} -d {pid}

As process {pid}, I am waiting for a debugger to attach.

Details:
  Host         : {hostname}
  Process      : {pid}
  Username     : {username}
  Command line : {argv}
  Traceback:
{traceback}
""".format(**d)
    else:
        email_body = """\
While running {argv_abbrev}, waitpoint reached at {filename}:{line}

Please run:
    ssh -t {hostname} {pydbg} -p {pid}

As process {originalpid}, I have forked to process {pid} and am waiting for a debugger to attach.

Details:
  Host             : {hostname}
  Original process : {originalpid}
  Forked process   : {pid}
  Username         : {username}
  Command line     : {argv}
  Traceback:
{traceback}
""".format(**d)
    msg = MIMEText(email_body)
    msg['Subject'] = (
        "ssh {hostname} pydbg -p {pid}"
        " # breakpoint in {argv_abbrev} at {filename}:{line}"
        ).format(**d)
    msg['From'] = user
    msg['To'] = mailto

    s = smtplib.SMTP("localhost")
    s.sendmail(user, [mailto], msg.as_string())
    s.quit()


def syscall_marker(msg):
    """
    Execute a dummy syscall that is visible in truss/strace.
    """
    try:
        s = ("/###        %s" % (msg,)).ljust(70)
        os.stat(s)
    except OSError:
        pass


def _signal_handler_breakpoint(signal_number, interrupted_frame):
    fd_tty = _dev_tty_fd()
    os.write(fd_tty, b"\nIntercepted SIGQUIT; entering debugger.  Resend ^\\ to dump core (and 'stty sane' to reset terminal settings).\n\n")
    frame = _get_caller_frame()
    enable_signal_handler_breakpoint(False)
    breakpoint(
        frame=frame,
        on_continue=enable_signal_handler_breakpoint)


def enable_signal_handler_breakpoint(enable=True):
    '''
    Install a signal handler for SIGQUIT so that Control-\ or external SIGQUIT
    enters debugger.  Suitable to be called from site.py.
    '''
    # Idea from bzrlib.breakin
    # (http://bazaar.launchpad.net/~bzr/bzr/trunk/annotate/head:/bzrlib/breakin.py)
    if enable:
        signal.signal(signal.SIGQUIT, _signal_handler_breakpoint)
    else:
        signal.signal(signal.SIGQUIT, signal.SIG_DFL)


def enable_exception_handler():
    '''
    Enable C{sys.excepthook = debug_exception} so that we automatically enter
    the debugger upon uncaught exceptions.
    '''
    sys.excepthook = debug_exception


# Handle SIGTERM with traceback+exit.
def _sigterm_handler(signum, frame):
    # faulthandler.dump_traceback(all_threads=True)
    import traceback
    traceback.print_stack()
    # raise SigTermReceived
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    os._exit(99) # shouldn't get here


def enable_sigterm_handler():
    signal.signal(signal.SIGTERM, _sigterm_handler)


def enable_faulthandler():
    try:
        import faulthandler
    except ImportError:
        pass
    else:
        # Print Python user-level stack trace upon SIGSEGV/etc.
        faulthandler.enable()


def add_debug_functions_to_builtins():
    '''
    Install breakpoint(), etc. in the builtin global namespace.
    '''
    import __builtin__
    functions_to_add = [
        'breakpoint',
        'debug_exception',
        'debug_on_exception',
        'debug_statement',
        'print_traceback',
        #'syscall_marker'
        'waitpoint',
    ]
    for name in functions_to_add:
        setattr(__builtin__, name, globals()[name])

# TODO: allow attaching remotely (winpdb/rpdb2) upon sigquit.  Or rpc like http://code.activestate.com/recipes/576515/
# TODO: http://sourceware.org/gdb/wiki/PythonGdb


def get_executable(pid):
    """
    Get the full path for the target process.

    @type pid:
      C{int}
    @rtype:
      L{Filename}
    """
    uname = os.uname()[0]
    if uname == 'Linux':
        result = os.readlink('/proc/%d/exe' % (pid,))
    elif uname == 'SunOS':
        result = os.readlink('/proc/%d/path/a.out' % (pid,))
    else:
        # Use psutil to try to answer this.  This should also work for the
        # above cases too, but it's simple enough to implement it directly and
        # avoid this dependency on those platforms.
        import psutil
        result = psutil.Process(pid).exe()
    result = Filename(result).real
    if not result.isfile:
        raise ValueError("Couldn't get executable for pid %s" % (pid,))
    if not result.isreadable:
        raise ValueError("Executable %s for pid %s is not readable"
                         % (result, pid))
    return result


_gdb_safe_chars = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789,./-_=+:;'[]{}\|`~!@#%^&*()<>? ")

def _escape_for_gdb(string):
    """
    Escape a string to make it safe for passing to gdb.
    """
    result = []
    for char in string:
        if char in _gdb_safe_chars:
            result.append(char)
        else:
            result.append("\\%s" % (oct(ord(char)),))
    return ''.join(result)


_memoized_dev_null_w = None
def _dev_null_w():
    """
    Return a file object opened for writing to /dev/null.
    Memoized.

    @rtype:
      C{file}
    """
    global _memoized_dev_null_w
    if _memoized_dev_null_w is None:
        _memoized_dev_null_w = open("/dev/null", 'w')
    return _memoized_dev_null_w


def inject(pid, statements, wait=True, show_gdb_output=False):
    """
    Execute C{statements} in a running Python process.

    @type pid:
      C{int}
    @param pid:
      Id of target process
    @type statements:
      Iterable of strings
    @param statements:
      Python statements to execute.
    @return:
      Then process ID of the gdb process if C{wait} is False; C{None} if
      C{wait} is True.
    """
    import subprocess
    os.kill(pid, 0) # raises OSError "No such process" unless pid exists
    if isinstance(statements, basestring):
        statements = (statements,)
    else:
        statements = tuple(statements)
    for statement in statements:
        if not isinstance(statement, basestring):
            raise TypeError(
                "Expected iterable of strings, not %r" % (type(statement),))
    # Based on
    # https://github.com/lmacken/pyrasite/blob/master/pyrasite/inject.py
    # TODO: add error checking
    # TODO: consider using lldb, especially on Darwin.
    gdb_commands = (
        [ 'PyGILState_Ensure()' ]
        + [ 'PyRun_SimpleString("%s")' % (_escape_for_gdb(statement),)
            for statement in statements ]
        + [ 'PyGILState_Release($1)' ])
    python_path = get_executable(pid)
    if "python" not in python_path.base:
        raise ValueError(
            "pid %s uses executable %s, which does not appear to be python"
            % (pid, python_path))
    # TODO: check that gdb is found and that the version is new enough (7.x)
    command = (
        ['gdb', str(python_path), '-p', str(pid), '-batch']
        + [ '-eval-command=call %s' % (c,) for c in gdb_commands ])
    output = None if show_gdb_output else _dev_null_w()
    process = subprocess.Popen(command, stdout=output, stderr=output)
    if wait:
        retcode = process.wait()
        if retcode:
            raise Exception(
                "Gdb command %r failed (exit code %r)"
                % (command, retcode))
    else:
        return process.pid


class Pty(object):
    def __init__(self):
        import pty
        self.master_fd, self.slave_fd = pty.openpty()
        self.ttyname = os.ttyname(self.slave_fd)

    def communicate(self):
        import tty
        import pty
        try:
            mode = tty.tcgetattr(pty.STDIN_FILENO)
            tty.setraw(pty.STDIN_FILENO)
            restore = True
        except tty.error:
            restore = False
        try:
            pty._copy(self.master_fd)
        finally:
            if restore:
                tty.tcsetattr(pty.STDIN_FILENO, tty.TCSAFLUSH, mode)
        os.close(self.master_fd)


def process_exists(pid):
    """
    Return whether C{pid} exists.

    @type pid:
      C{int}
    @rtype:
      C{bool}
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            return False
        raise


def kill_process(pid, kill_signals):
    """
    Kill process C{pid} using various signals.

    @param kill_signals:
      Sequence of (signal, delay) tuples.  Each signal is tried in sequence,
      waiting up to C{delay} seconds before trying the next signal.
    """
    for sig, delay in kill_signals:
        start_time = time.time()
        try:
            os.kill(pid, sig)
        except OSError as e:
            if e.errno == errno.ESRCH:
                return True
            raise
        deadline = start_time + delay
        while time.time() < deadline:
            if not process_exists(pid):
                return True
            time.sleep(0.05)


def attach_debugger(pid):
    """
    Attach command-line debugger to a running process.

    @param pid:
      Process id of target process.
    """
    import pyflyby
    import signal
    class SigUsr1(Exception):
        pass
    def sigusr1_handler(*args):
        raise SigUsr1
    signal.signal(signal.SIGUSR1, sigusr1_handler)
    terminal = Pty()
    pyflyby_lib_path = os.path.dirname(pyflyby.__path__[0])
    # Inject the statement 'breakpoint()' into target process.
    # Signal ourselves that we're done.  TODO: what's a better way to
    # do this?
    on_continue = "lambda: os.kill(%d, %d)" % (os.getpid(), signal.SIGUSR1)
    gdb_pid = inject(pid, [
            "import sys",
            "sys.path.insert(0, %r)" % (pyflyby_lib_path,),
            "import pyflyby",
            ("pyflyby.breakpoint(tty=%r, on_continue=%s)"
             % (terminal.ttyname, on_continue)),
            ], wait=False)
    # Fork a watchdog process to make sure we exit if the target process or
    # gdb process exits, and make sure the gdb process exits if we exit.
    parent_pid = os.getpid()
    watchdog_pid = os.fork()
    if watchdog_pid == 0:
        while True:
            if not process_exists(gdb_pid):
                kill_process(
                    parent_pid,
                    [(signal.SIGUSR1, 5), (signal.SIGTERM, 15),
                     (signal.SIGKILL, 60)])
                break
            if not process_exists(pid):
                start_time = time.time()
                os.kill(parent_pid, signal.SIGUSR1)
                kill_process(
                    gdb_pid,
                    [(0, 5), (signal.SIGTERM, 15), (signal.SIGKILL, 60)])
                kill_process(
                    parent_pid,
                    [(0, (5 + time.time() - start_time)),
                     (signal.SIGTERM, 15), (signal.SIGKILL, 60)])
                break
            if not process_exists(parent_pid):
                kill_process(
                    gdb_pid,
                    [(0, 5), (signal.SIGTERM, 15), (signal.SIGKILL, 60)])
                break
            time.sleep(0.1)
        os._exit(0)
    # Communicate with pseudo tty.
    try:
        terminal.communicate()
    except SigUsr1:
        print("Debugging complete.")
        pass


def remote_print_stack(pid, output=1):
    """
    Tell a target process to print a stack trace.

    This currently only handles the main thread.
    TODO: handle multiple threads.

    @param pid:
      PID of target process.
    @type output:
      C{int}, C{file}, or C{str}
    @param output:
      Output file descriptor.
    """
    # Interpret C{output} argument as a file-like object, file descriptor, or
    # filename.
    if hasattr(output, 'write'): # file-like object
        output_fh = output
        try:
            output.flush()
        except Exception:
            pass
        try:
            output_fd = output.fileno()
        except Exception:
            output_fd = None
        try:
            output_fn = Filename(output.name)
        except Exception:
            pass
    elif isinstance(output, int):
        output_fh = None
        output_fn = None
        output_fd = output
    elif isinstance(output, (str, Filename)):
        output_fh = None
        output_fn = Filename(output)
        output_fd = None
    else:
        raise TypeError(
            "remote_print_stack_trace(): expected file/str/int; got %s"
            % (type(output).__name__,))
    temp_file = None
    remote_fn = output_fn
    if remote_fn is None and output_fd is not None:
        remote_fn = Filename("/proc/%d/fd/%d" % (os.getpid(), output_fd))
    # Figure out whether the target process will be able to open output_fn for
    # writing.  Since the target process would need to be running as the same
    # user as this process for us to be able to attach a debugger, we can
    # simply check whether we ourselves can open the file.  Typically output
    # will be fd 1 and we will have access to write to it.  However, if we're
    # sudoed, we won't be able to re-open it via the proc symlink, even though
    # we already currently have it open.  Another case is C{output} is a
    # file-like object that isn't a real file, e.g. a StringO.  In each case
    # we we don't have a usable filename for the remote process yet.  To
    # address these situations, we create a temporary file for the remote
    # process to write to.
    if remote_fn is None or not remote_fn.iswritable:
        if not output_fh or output_fd:
            assert remote_fn is not None
            raise OSError(errno.EACCESS, "Can't write to %s" % output_fn)
        # We can still use the /proc/$pid/fd approach with an unnamed temp
        # file.  If it turns out there are situations where that doesn't work,
        # we can switch to using a NamedTemporaryFile.
        from tempfile import TemporaryFile
        temp_file = TemporaryFile()
        remote_fn = Filename(
            "/proc/%d/fd/%d" % (os.getpid(), temp_file.fileno()))
        assert remote_fn.iswritable
    # *** Do the code injection ***
    _remote_print_stack_to_file(pid, remote_fn)
    # Copy from temp file to the requested output.
    if temp_file is not None:
        data = temp_file.read()
        temp_file.close()
        if output_fh is not None:
            output_fh.write(data)
            output_fh.flush()
        elif output_fd is not None:
            with os.fdopen(output_fd, 'w') as f:
                f.write(data)
        else:
            raise AssertionError("unreacahable")


def _remote_print_stack_to_file(pid, filename):
    inject(pid, [
        "import traceback",
        "with open(%r,'w') as f: traceback.print_stack(file=f)" % str(filename)
        ], wait=True)
