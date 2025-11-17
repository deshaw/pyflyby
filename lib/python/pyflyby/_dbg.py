# pyflyby/_dbg.py.
# Copyright (C) 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


import builtins
from   contextlib               import contextmanager
import errno
from   functools                import wraps
import os
import pwd
import signal
import sys
import time
from   types                    import CodeType, FrameType, TracebackType

from   collections.abc          import Callable

from   pyflyby._file            import Filename


"""
Used by wait_for_debugger_to_attach to record whether we're waiting to attach,
and if so what.
"""
_waiting_for_debugger = None


_ORIG_SYS_EXCEPTHOOK = sys.excepthook

def _reset_excepthook():
    if _ORIG_SYS_EXCEPTHOOK:
        sys.excepthook = _ORIG_SYS_EXCEPTHOOK
        return True
    return False


def _override_excepthook(hook):
    """
    Override sys.excepthook with `hook` but also support resetting.

    Users should call this function instead of directly overiding
    sys.excepthook. This is helpful in resetting sys.excepthook in certain cases.
    """
    global _ORIG_SYS_EXCEPTHOOK
    _ORIG_SYS_EXCEPTHOOK = hook
    sys.excepthook = hook


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


def tty_is_usable():
    """
    Return whether /dev/tty is usable.

    In interactive sessions, /dev/tty is usable; in non-interactive sessions,
    /dev/tty is not usable::

      $ ssh -t localhost py -q pyflyby._dbg.tty_is_usable
      True

      $ ssh -T localhost py -q pyflyby._dbg.tty_is_usable
      False

    tty_is_usable() is useful for deciding whether we are in an interactive
    terminal.  In an interactive terminal we can enter the debugger directly;
    in a non-interactive terminal, we need to wait_for_debugger_to_attach.

    Note that this is different from doing e.g. isatty(0).  isatty would
    return False if a program was piped, even though /dev/tty is usable.
    """
    try:
        _dev_tty_fd()
        return True
    except _NoTtyError:
        return False


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

    :type tty:
      ``int`` or ``str``
    :param tty:
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
        from ._util import nested
        with nested(_FdCtx(0, fd), _FdCtx(1, fd), _FdCtx(2, fd)):
            with nested(os.fdopen(0, 'r'),
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
    Context manager that restores ``sys.excepthook`` upon exit.
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
    Context manager that resets ``sys.displayhook`` to the default value upon
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

    :param exc_info:
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

    :return:
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

    :rtype:
      ``FrameType``
    '''
    this_filename = _get_caller_frame.__code__.co_filename
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


def _prompt_continue_waiting_for_debugger():
    """
    Prompt while exiting the debugger to get user opinion on keeping the
    process waiting for debugger to attach.
    """
    count_invalid = 0
    max_invalid_entries = 3
    while count_invalid < max_invalid_entries:
        sys.stdout.flush()
        response = input("Keep the process running for debugger to be "
                            "attached later ? (y)es/(n)o\n")

        if response.lower() in ('n', 'no'):
            global _waiting_for_debugger
            _waiting_for_debugger = None
            break

        if response.lower() not in ('y', 'yes'):
            print("Invalid response: {}".format(repr(response)))
            count_invalid += 1
        else:
            break
    else:
        print("Exiting after {} invalid responses.".format(max_invalid_entries))
        _waiting_for_debugger = None
        # Sleep for a fraction of second for the print statements to get printed.
        time.sleep(0.01)


def _debug_exception(*exc_info, **kwargs):
    """
    Debug an exception -- print a stack trace and enter the debugger.

    Suitable to be assigned to sys.excepthook.
    """
    from pyflyby._interactive import print_verbose_tb
    tty = kwargs.pop("tty", "/dev/tty")
    debugger_attached = kwargs.pop("debugger_attached", False)
    if kwargs:
        raise TypeError("debug_exception(): unexpected kwargs %s"
                        % (', '.join(sorted(kwargs.keys()))))
    if not exc_info:
        exc_info = sys.exc_info()
    if len(exc_info) == 1 and type(exc_info[0]) is tuple:
        exc_info = exc_info[0]
    if len(exc_info) == 1 and type(exc_info[0]) is TracebackType:
        # Allow the input to be just the traceback.  The exception instance is
        # only used for printing the traceback.  It's not needed by the
        # debugger.
        # We don't know the exception in this case.  For now put "", "".  This
        # will cause print_verbose_tb to include a line with just a colon.
        # TODO: avoid that line.
        exc_info = ("", "", exc_info)
    if exc_info[1]:
        # Explicitly set sys.last_value / sys.last_exc to ensure they are available
        # in the debugger. One use case is that this allows users to call
        # pyflyby.saveframe() within the debugger.
        if sys.version_info < (3, 12):
            sys.last_value = exc_info[1]
        else:
            sys.last_exc = exc_info[1]

    with _DebuggerCtx(tty=tty) as pdb:
        if debugger_attached:
            # If debugger is attached to the process made waiting by
            # 'wait_for_debugger_to_attach', check with the user whether to
            # keep the process waiting for debugger to attach.
            pdb.postloop = _prompt_continue_waiting_for_debugger
        print_verbose_tb(*exc_info)
        # Starting Py3.13, pdb.interaction() supports chained exceptions in case
        # exception (and not traceback) is specified. This support is backported
        # to IPython8.16 for earlier Python versions. So the conditions where
        # chained exceptions won't be supported from here would be with the
        # Python version < 3.13 and ipython not installed, or IPython's version
        # is lesser than 8.16.
        tb_or_exc = exc_info[2]
        if sys.version_info < (3, 13):
            # Check if the instance is of IPython's Pdb and its version.
            try:
                import IPython
                if IPython.version_info >= (8, 16):
                    from IPython.core.debugger import Pdb as IPdb
                    # This is expected to be True, hence just a safe check.
                    if isinstance(pdb, IPdb):
                        tb_or_exc = exc_info[1]
            except ModuleNotFoundError:
                pass
        else:
            tb_or_exc = exc_info[1]
        pdb.interaction(None, tb_or_exc)


def _debug_code(arg, globals=None, locals=None, auto_import=True, tty="/dev/tty"):
    """
    Run code under the debugger.

    :type arg:
      ``str``, ``Callable``, ``CodeType``, ``PythonStatement``, ``PythonBlock``,
      ``FileText``
    """
    if globals is None or locals is None:
        caller_frame = _get_caller_frame()
        if globals is None:
            globals = caller_frame.f_globals
        if locals is None:
            locals = caller_frame.f_locals
        del caller_frame
    with _DebuggerCtx(tty=tty) as pdb:
        print("Entering debugger.  Use 'n' to step, 'c' to run, 'q' to stop.")
        print("")
        from ._parse import PythonStatement, PythonBlock, FileText

        if isinstance(arg, (str, PythonStatement, PythonBlock, FileText)):
            # Compile the block so that we can get the right compile mode.
            arg = PythonBlock(arg)
            # TODO: enter text into linecache
            autoimp_arg = arg
            code = arg.compile()
        elif isinstance(arg, CodeType):
            autoimp_arg = arg
            code = arg
        elif isinstance(arg, Callable):
            # TODO: check argspec to make sure it's a zero-arg callable.
            code = arg.__code__
            autoimp_arg = code
        else:
            raise TypeError(
                "debug_code(): expected a string/callable/lambda; got a %s"
                % (type(arg).__name__,))
        if auto_import:
            from ._autoimp import auto_import as auto_import_f
            auto_import_f(autoimp_arg, [globals, locals])
        return pdb.runeval(code, globals=globals, locals=locals)


_CURRENT_FRAME = object()


def debugger(*args, **kwargs):
    '''
    Entry point for debugging.

    ``debugger()`` can be used in the following ways::

    1. Breakpoint mode, entering debugger in executing code::
         >> def foo():
         ..     bar()
         ..     debugger()
         ..     baz()

       This allow stepping through code after the debugger() call - i.e. between
       bar() and baz().  This is similar to 'import pdb; pdb.set_trace()'::

    2. Debug a python statement::

         >> def foo(x):
         ..     ...
         >> X = 5

         >> debugger("foo(X)")

       The auto-importer is run on the given python statement.

    3. Debug a callable::

         >> def foo(x=5):
         ..     ...

         >> debugger(foo)
         >> debugger(lambda: foo(6))

    4. Debug an exception::

         >> try:
         ..     ...
         .. except:
         ..     debugger(sys.exc_info())


    If the process is waiting on for a debugger to attach to debug a frame or
    exception traceback, then calling debugger(None) will debug that target.
    If it is frame, then the user can step through code.  If it is an
    exception traceback, then the debugger will operate in post-mortem mode
    with no stepping allowed.  The process will continue running after this
    debug session's "continue".

    ``debugger()`` is suitable to be called interactively, from scripts, in
    sys.excepthook, and in signal handlers.

    :param args:
      What to debug:
        - If a string or callable, then run it under the debugger.
        - If a frame, then debug the frame.
        - If a traceback, then debug the traceback.
        - If a 3-tuple as returned by sys.exc_info(), then debug the traceback.
        - If the process is waiting to for a debugger to attach, then attach
          the debugger there.  This is only relevant when an external process
          is attaching a debugger.
        - If nothing specified, then enter the debugger at the statement
          following the call to debug().
    :kwarg tty:
      Tty to connect to.  If ``None`` (default): if /dev/tty is usable, then
      use it; else call wait_for_debugger_to_attach() instead (unless
      wait_for_attach==False).
    :kwarg on_continue:
      Function to call upon exiting the debugger and continuing with regular
      execution.
    :kwarg wait_for_attach:
      Whether to wait for a remote terminal to attach (with 'py -d PID').
      If ``True``, then always wait for a debugger to attach.
      If ``False``, then never wait for a debugger to attach; debug in the
      current terminal.
      If unset, then defaults to true only when ``tty`` is unspecified and
      /dev/tty is not usable.
    :kwarg background:
      If ``False``, then pause execution to debug.
      If ``True``, then fork a process and wait for a debugger to attach in the
      forked child.
    '''
    from ._parse import PythonStatement, PythonBlock, FileText
    if len(args) in {1, 2}:
        arg = args[0]
    elif len(args) == 0:
        arg = None
    else:
        arg = args
    tty             = kwargs.pop("tty"            , None)
    on_continue     = kwargs.pop("on_continue"    , lambda: None)
    globals         = kwargs.pop("globals"        , None)
    locals          = kwargs.pop("locals"         , None)
    wait_for_attach = kwargs.pop("wait_for_attach", Ellipsis)
    background      = kwargs.pop("background"     , False)
    _debugger_attached = False
    if kwargs:
        raise TypeError("debugger(): unexpected kwargs %s"
                        % (', '.join(sorted(kwargs))))
    if arg is None and tty is not None and wait_for_attach != True:
        # If _waiting_for_debugger is not None, then attach to that
        # (whether it's a frame, traceback, etc).
        arg = _waiting_for_debugger
        _debugger_attached = True
    if arg is None:
        # Debug current frame.
        arg = _CURRENT_FRAME
    if arg is _CURRENT_FRAME:
        arg = _get_caller_frame()
    if background:
        # Fork a process and wait for a debugger to attach in the background.
        # Todo: implement on_continue()
        wait_for_debugger_to_attach(arg, background=True)
        return
    if wait_for_attach == True:
        wait_for_debugger_to_attach(arg)
        return
    if tty is None:
        if tty_is_usable():
            tty = "/dev/tty"
        elif wait_for_attach != False:
            # If the tty isn't usable, then default to waiting for the
            # debugger to attach from another (interactive) terminal.
            # Todo: implement on_continue()
            # TODO: capture globals/locals when relevant.
            wait_for_debugger_to_attach(arg)
            return
    if isinstance(
        arg, (str, PythonStatement, PythonBlock, FileText, CodeType, Callable)
    ):
        _debug_code(arg, globals=globals, locals=locals, tty=tty)
        on_continue()
        return
    if (isinstance(arg, TracebackType) or
        type(arg) is tuple and len(arg) == 3 and type(arg[2]) is TracebackType):
        _debug_exception(arg, tty=tty, debugger_attached=_debugger_attached)
        on_continue()
        return
    import threading
    # If `arg` is an instance of `tuple` that contains
    # `threading.ExceptHookArgs`, extract the exc_info from it.
    if type(arg) is tuple and len(arg) == 1 and type(arg[0]) is threading.ExceptHookArgs:
        arg = arg[0][:3]
        _debug_exception(arg, tty=tty, debugger_attached=_debugger_attached)
        on_continue()
        return
    if not isinstance(arg, FrameType):
        raise TypeError(
            "debugger(): expected a frame/traceback/str/code; got %s"
            % (arg,))
    frame = arg
    if globals is not None or locals is not None:
        raise NotImplementedError(
            "debugger(): globals/locals only relevant when debugging code")
    pdb_context = _DebuggerCtx(tty)
    pdb = pdb_context.__enter__()
    print("Entering debugger.  Use 'n' to step, 'c' to continue running, 'q' to quit Python completely.")
    def set_continue():
        # Continue running code outside the debugger.
        pdb.stopframe = pdb.botframe
        pdb.returnframe = None
        sys.settrace(None)
        print("Continuing execution.")
        pdb_context.__exit__(None, None, None)
        on_continue()
    def set_quit():
        # Quit the program.  Note that if we're inside IPython, then this
        # won't actually exit IPython.  We do want to call the context
        # __exit__ here to make sure we restore sys.displayhook, etc.
        # TODO: raise something else here if in IPython
        pdb_context.__exit__(None, None, None)
        raise SystemExit("Quitting as requested while debugging.")
    pdb.set_continue = set_continue
    pdb.set_quit = set_quit
    pdb.do_EOF = pdb.do_continue
    pdb.set_trace(frame)
    # Note: set_trace() installs a tracer and returns; that means we can't use
    # context managers around set_trace(): the __exit__() would be called
    # right away, not after continuing/quitting.
    # We also want this to be the very last thing called in the function (and
    # not in a nested function).  This way the very next thing the user sees
    # is his own code.



_cached_py_commandline = None
def _find_py_commandline():
    global _cached_py_commandline
    if _cached_py_commandline is not None:
        return _cached_py_commandline
    import pyflyby
    pkg_path = Filename(pyflyby.__path__[0]).real
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



class DebuggerAttachTimeoutError(Exception):
    pass


def _sleep_until_debugger_attaches(arg, timeout=86400):
    assert arg is not None
    global _waiting_for_debugger
    try:
        deadline = time.time() + timeout
        _waiting_for_debugger = arg
        while _waiting_for_debugger is not None:
            if time.time() > deadline:
                raise DebuggerAttachTimeoutError
            time.sleep(0.5)
    finally:
        _waiting_for_debugger = None


def wait_for_debugger_to_attach(arg, mailto=None, background=False, timeout=86400):
    """
    Send email to user and wait for debugger to attach.

    :param arg:
      What to debug.  Should be a sys.exc_info() result or a sys._getframe()
      result.
    :param mailto:
      Recipient to email.  Defaults to $USER or current user.
    :param background:
      If True, fork a child process.  The parent process continues immediately
      without waiting.  The child process waits for a debugger to attach, and
      exits when the debugging session completes.
    :param timeout:
      Maximum number of seconds to wait for user to attach debugger.
    """
    import traceback
    if background:
        originalpid = os.getpid()
        if os.fork() != 0:
            return
    else:
        originalpid = None
    try:
        # Reset the exception hook after the first exception.
        #
        # In case the code injected by the remote client causes some error in
        # the debugged process, another email is sent for the new exception. This can
        # lead to an infinite loop of sending mail for each successive exceptions
        # everytime a remote client tries to connect. Our process might never get
        # a chance to exit and the remote client might just hang.
        #
        if not _reset_excepthook():
            raise ValueError("Couldn't reset sys.excepthook. Aborting remote "
                             "debugging.")
        # Send email.
        _send_email_with_attach_instructions(arg, mailto, originalpid=originalpid)
        # Sleep until the debugger to attaches.
        _sleep_until_debugger_attaches(arg, timeout=timeout)
    except:
        traceback.print_exception(*sys.exc_info())
    finally:
        if background:
            # Exit.  Note that the original process already continued.
            # We do this in a 'finally' to make sure that we always exit
            # here.  We don't want to do cleanup actions (finally clauses,
            # atexit functions) in the parent, since that can affect the
            # parent (e.g. deleting temp files while the parent process is
            # still using them).
            os._exit(1)


def debug_on_exception(function, background=False):
    """
    Decorator that wraps a function so that we enter a debugger upon exception.
    """
    @wraps(function)
    def wrapped_function(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            debugger(sys.exc_info(), background=background)
            raise
    return wrapped_function


def _send_email_with_attach_instructions(arg, mailto, originalpid):
    from   email.mime.text import MIMEText
    import smtplib
    import socket
    import traceback
    # Prepare variables we'll use in the email.
    d = dict()
    user = pwd.getpwuid(os.geteuid()).pw_name
    argv = ' '.join(sys.argv)
    d.update(
        argv       =argv                  ,
        argv_abbrev=argv[:40]             ,
        event      ="breakpoint"          ,
        exc        =None                  ,
        exctype    =None                  ,
        hostname   =socket.getfqdn()      ,
        originalpid=originalpid           ,
        pid        =os.getpid()           ,
        py         =_find_py_commandline(),
        time       =time.strftime("%Y-%m-%d %H:%M:%S %Z", time.localtime()),
        traceback  =None                  ,
        username   =user                  ,
    )
    tb = None
    frame = None
    stacktrace = None
    if isinstance(arg, FrameType):
        frame       = arg
        stacktrace = ''.join(traceback.format_stack(frame))
    elif isinstance(arg, TracebackType):
        frame = d['tb'].tb_frame
        stacktrace = ''.join(traceback.format_tb(arg))
    elif isinstance(arg, tuple) and len(arg) == 3 and isinstance(arg[2], TracebackType):
        d.update(
            exctype=arg[0].__name__,
            exc    =arg[1]         ,
            event  =arg[0].__name__,
        )
        tb = arg[2]
        while tb.tb_next:
            tb = tb.tb_next
        frame = tb.tb_frame
        stacktrace = ''.join(traceback.format_tb(arg[2])) + (
            "  %s: %s\n" % (arg[0].__name__, arg[1]))
    if not frame:
        frame = _get_caller_frame()
    d.update(
        function = frame.f_code.co_name    ,
        filename = frame.f_code.co_filename,
        line     = frame.f_lineno          ,
    )
    d.update(
        filename_abbrev = _abbrev_filename(d['filename']),
    )
    if tb:
        d['stacktrace'] = tb and ''.join("    %s\n" % (line,) for line in stacktrace.splitlines())
    # Construct a template for the email body.
    template = []
    template += [
        "While running {argv_abbrev}, {event} in {function} at {filename}:{line}",
        "",
        "Please run:",
        "    ssh -t {hostname} {py} -d {pid}",
        "",
    ]
    if d['originalpid']:
        template += [
            "As process {originalpid}, I have forked to process {pid} and am waiting for a debugger to attach."
        ]
    else:
        template += [
            "As process {pid}, I am waiting for a debugger to attach."
        ]
    template += [
        "",
        "Details:",
        "  Time             : {time}",
        "  Host             : {hostname}",
    ]
    if d['originalpid']:
        template += [
            "  Original process : {originalpid}",
            "  Forked process   : {pid}",
        ]
    else:
        template += [
            "  Process          : {pid}",
        ]
    template += [
        "  Username         : {username}",
        "  Command line     : {argv}",
    ]
    if d['exc']:
        template += [
            "  Exception        : {exctype}: {exc}",
        ]
    if d.get('stacktrace'):
        template += [
            "  Traceback        :",
            "{stacktrace}",
        ]
    # Build email body.
    email_body = '\n'.join(template).format(**d)
    # Print to stderr.
    prefixed = "".join("[PYFLYBY] %s\n" % line
                       for line in email_body.splitlines())
    sys.stderr.write(prefixed)
    # Send email.
    if mailto is None:
        mailto = os.getenv("USER") or user
    msg = MIMEText(email_body)
    msg['Subject'] = (
        "ssh {hostname} py -d {pid}"
        " # {event} in {argv_abbrev} in {function} at {filename_abbrev}:{line}"
        ).format(**d)
    msg['From'] = user
    msg['To'] = mailto
    s = smtplib.SMTP("localhost")
    s.sendmail(user, [mailto], msg.as_string())
    s.quit()


def _abbrev_filename(filename):
    splt = filename.rsplit("/", 4)
    if len(splt) >= 4:
        splt[:2] = ["..."]
    return '/'.join(splt)


def syscall_marker(msg):
    """
    Execute a dummy syscall that is visible in truss/strace.
    """
    try:
        s = ("/###        %s" % (msg,)).ljust(70)
        os.stat(s)
    except OSError:
        pass


_ORIG_PID = os.getpid()

def _signal_handler_debugger(signal_number, interrupted_frame):
    if os.getpid() != _ORIG_PID:
        # We're in a forked subprocess.  Ignore this SIGQUIT.
        return
    fd_tty = _dev_tty_fd()
    os.write(fd_tty, b"\nIntercepted SIGQUIT; entering debugger.  Resend ^\\ to dump core (and 'stty sane' to reset terminal settings).\n\n")
    frame = _get_caller_frame()
    enable_signal_handler_debugger(False)
    debugger(
        frame,
        on_continue=enable_signal_handler_debugger)
    signal.signal(signal.SIGQUIT, _signal_handler_debugger)


def enable_signal_handler_debugger(enable=True):
    r'''
    Install a signal handler for SIGQUIT so that Control-\ or external SIGQUIT
    enters debugger.  Suitable to be called from site.py.
    '''
    # Idea from bzrlib.breakin
    # (http://bazaar.launchpad.net/~bzr/bzr/trunk/annotate/head:/bzrlib/breakin.py)
    if enable:
        signal.signal(signal.SIGQUIT, _signal_handler_debugger)
    else:
        signal.signal(signal.SIGQUIT, signal.SIG_DFL)


def enable_exception_handler_debugger():
    '''
    Enable ``sys.excepthook = debugger`` so that we automatically enter
    the debugger upon uncaught exceptions.
    '''
    _override_excepthook(debugger)


# Handle SIGTERM with traceback+exit.
def _sigterm_handler(signum, frame):
    # faulthandler.dump_traceback(all_threads=True)
    import traceback
    traceback.print_stack()
    # raise SigTermReceived
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)
    os._exit(99) # shouldn't get here


def enable_sigterm_handler(on_existing_handler='raise'):
    """
    Install a handler for SIGTERM that causes Python to print a stack trace
    before exiting.

    :param on_existing_handler:
      What to do when a SIGTERM handler was already registered.
        - If ``"raise"``, then keep the existing handler and raise an exception.
        - If ``"keep_existing"``, then silently keep the existing handler.
        - If ``"warn_and_override"``, then override the existing handler and log a warning.
        - If ``"silently_override"``, then silently override the existing handler.
    """
    old_handler = signal.signal(signal.SIGTERM, _sigterm_handler)
    if old_handler == signal.SIG_DFL or old_handler == _sigterm_handler:
        return
    if on_existing_handler == "silently_override":
        return
    if on_existing_handler == "warn_and_override":
        from ._log import logger
        logger.warning("enable_sigterm_handler(): Overriding existing SIGTERM handler")
        return
    signal.signal(signal.SIGTERM, old_handler)
    if on_existing_handler == "keep_existing":
        return
    elif on_existing_handler == "raise":
        raise ValueError(
            "enable_sigterm_handler(on_existing_handler='raise'): SIGTERM handler already exists" + repr(old_handler))
    else:
        raise ValueError(
            "enable_sigterm_handler(): SIGTERM handler already exists, "
            "and invalid on_existing_handler=%r"
            % (on_existing_handler,))


def enable_faulthandler():
    try:
        import faulthandler
    except ImportError:
        pass
    else:
        # Print Python user-level stack trace upon SIGSEGV/etc.
        faulthandler.enable()


def add_debug_functions_to_builtins(*, add_deprecated: bool):
    """
    Install debugger(), etc. in the builtin global namespace.
    """
    functions_to_add = [
        'debugger',
        'debug_on_exception',
        'print_traceback',
    ]
    if add_deprecated:
        # DEPRECATED: In the future, the following will not be added to builtins.
        # Use debugger() instead.
        functions_to_add += [
            "breakpoint",
            "debug_exception",
            "debug_statement",
            "waitpoint",
        ]
    for name in functions_to_add:
        setattr(builtins, name, globals()[name])

# TODO: allow attaching remotely (winpdb/rpdb2) upon sigquit.  Or rpc like http://code.activestate.com/recipes/576515/
# TODO: http://sourceware.org/gdb/wiki/PythonGdb


def get_executable(pid):
    """
    Get the full path for the target process.

    :type pid:
      ``int``
    :rtype:
      `Filename`
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
    r"0123456789,./-_=+:;'[]{}\|`~!@#%^&*()<>? ")

def _escape_for_gdb(string):
    """
    Escape a string to make it safe for passing to gdb.
    """
    result = []
    for char in string:
        if char in _gdb_safe_chars:
            result.append(char)
        else:
            result.append(r"\0{0:o}".format(ord(char)))
    return ''.join(result)


_memoized_dev_null = None
def _dev_null():
    """
    Return a file object opened for reading/writing to /dev/null.
    Memoized.

    :rtype:
      ``file``
    """
    global _memoized_dev_null
    if _memoized_dev_null is None:
        _memoized_dev_null = open("/dev/null", 'w+')
    return _memoized_dev_null


def inject(pid, statements, wait=True, show_gdb_output=False):
    """
    Execute ``statements`` in a running Python process.

    :type pid:
      ``int``
    :param pid:
      Id of target process
    :type statements:
      Iterable of strings
    :param statements:
      Python statements to execute.
    :return:
      Then process ID of the gdb process if ``wait`` is False; ``None`` if
      ``wait`` is True.
    """
    import subprocess
    os.kill(pid, 0) # raises OSError "No such process" unless pid exists

    # Check if we have permissions to attach to the process before proceeding
    try:
        subprocess.run(
            ["gdb", "-n", "-batch", "--interpreter=mi", "-p", str(pid)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        raise Exception(
            f"Unable to attach to pid {pid} with gdb (exit code {e.returncode}). "
            f"Reason: {e.stderr.decode()}"
        ) from e

    if isinstance(statements, str):
        statements = (statements,)
    else:
        statements = tuple(statements)
    for statement in statements:
        if not isinstance(statement, str):
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
    #
    # A note about --interpreter=mi: mi stands for Machine Interface and it's
    # the blessed way to control gdb from a pipe, since the output is much
    # easier to parse than the normal human-oriented output (it is also worth
    # noting that at the moment we are never parsig the output, but it's still
    # a good practice to use --interpreter=mi).
    command = (
        ['gdb', '-n', str(python_path), '-p', str(pid), '-batch', '--interpreter=mi']
        + [ '-eval-command=call %s' % (c,) for c in gdb_commands ])

    output = subprocess.PIPE if show_gdb_output else _dev_null()

    process = subprocess.Popen(command,
                               stdin=_dev_null(),
                               stdout=output,
                               stderr=output)
    if wait:
        retcode = process.wait()
        if retcode:
            raise Exception(
                "Gdb command %r failed (exit code %r)"
                % (command, retcode))
    else:
        return process.pid

import tty


# Copy of tty.setraw that does not set ISIG,
# in order to keep CTRL-C sending Keybord Interrupt.
def setraw_but_sigint(fd, when=tty.TCSAFLUSH):
    """Put terminal into a raw mode."""
    mode = tty.tcgetattr(fd)
    mode[tty.IFLAG] = mode[tty.IFLAG] & ~(
        tty.BRKINT | tty.ICRNL | tty.INPCK | tty.ISTRIP | tty.IXON
    )
    mode[tty.OFLAG] = mode[tty.OFLAG] & ~(tty.OPOST)
    mode[tty.CFLAG] = mode[tty.CFLAG] & ~(tty.CSIZE | tty.PARENB)
    mode[tty.CFLAG] = mode[tty.CFLAG] | tty.CS8
    mode[tty.LFLAG] = mode[tty.LFLAG] & ~(
        tty.ECHO | tty.ICANON | tty.IEXTEN
    )  # NOT ISIG HERE.
    mode[tty.CC][tty.VMIN] = 1
    mode[tty.CC][tty.VTIME] = 0
    tty.tcsetattr(fd, when, mode)


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
            setraw_but_sigint(pty.STDIN_FILENO)
            restore = True
        except tty.error:
            restore = False
        try:
            pty._copy(self.master_fd)
        except KeyboardInterrupt:
            print('^C\r') # we need the \r because we are still in raw mode
        finally:
            if restore:
                tty.tcsetattr(pty.STDIN_FILENO, tty.TCSAFLUSH, mode)
        os.close(self.master_fd)


def process_exists(pid):
    """
    Return whether ``pid`` exists.

    :type pid:
      ``int``
    :rtype:
      ``bool``
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
    Kill process ``pid`` using various signals.

    :param kill_signals:
      Sequence of (signal, delay) tuples.  Each signal is tried in sequence,
      waiting up to ``delay`` seconds before trying the next signal.
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

    :param pid:
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
    # Inject a call to 'debugger()' into target process.
    # Set on_continue to signal ourselves that we're done.
    on_continue = "lambda: __import__('os').kill(%d, %d)" % (os.getpid(), signal.SIGUSR1)

    # Use Python import machinery to import pyflyby from its directory.
    #
    # Adding the path to sys.path might have side effects. For e.g., a package
    # with the same name as a built-in module could exist in `pyflyby_dir`.
    # Adding `pyflyby_dir` to sys.path will make the package get imported from
    # `pyflyby_dir` instead of deferring this decision to the user Python
    # environment.
    #
    # As a concrete example, `typing` module is a package as well a built-in
    # module from Python version >= 3.5
    statements = [
        "loader = __import__('importlib').machinery.PathFinder.find_module("
        "fullname='pyflyby', path=['{pyflyby_dir}'])".format(
            pyflyby_dir=pyflyby_lib_path),
        "pyflyby = loader.load_module('pyflyby')"
    ]
    statements.append(
        ("pyflyby.debugger(tty=%r, on_continue=%s)"
         % (terminal.ttyname, on_continue))
        )

    gdb_pid = inject(pid, statements=";".join(statements), wait=False)
    # Fork a watchdog process to make sure we exit if the target process or
    # gdb process exits, and make sure the gdb process exits if we exit.
    parent_pid = os.getpid()
    watchdog_pid = os.fork()
    if watchdog_pid == 0:
        while True:
            try:
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
            except KeyboardInterrupt:
                # if the user pressed CTRL-C the parent process is about to
                # die, so we will detect the death in the next iteration of
                # the loop and exit cleanly after killing also gdb
                pass
        os._exit(0)
    # Communicate with pseudo tty.
    try:
        terminal.communicate()
    except SigUsr1:
        print("\nDebugging complete.")
        pass


def remote_print_stack(pid, output=1):
    """
    Tell a target process to print a stack trace.

    This currently only handles the main thread.
    TODO: handle multiple threads.

    :param pid:
      PID of target process.
    :type output:
      ``int``, ``file``, or ``str``
    :param output:
      Output file descriptor.
    """
    # Interpret ``output`` argument as a file-like object, file descriptor, or
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
    # we already currently have it open.  Another case is ``output`` is a
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



# Deprecated wrapper for wait_for_debugger_to_attach().
def waitpoint(frame=None, mailto=None, background=False, timeout=86400):
    if frame is None:
        frame = _get_caller_frame()
    wait_for_debugger_to_attach(frame, mailto=mailto,
                                background=background, timeout=timeout)

breakpoint                       = debugger                          # deprecated alias
debug_statement                  = debugger                          # deprecated alias
debug_exception                  = debugger                          # deprecated alias
enable_signal_handler_breakpoint = enable_signal_handler_debugger    # deprecated alias
enable_exception_handler         = enable_exception_handler_debugger # deprecated alias
