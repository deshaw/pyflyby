# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

from   contextlib               import contextmanager
import logging
from   logging                  import Handler, Logger
import os
import sys


class _PyflybyHandler(Handler):

    _pre_log_function = None
    _logged_anything_during_context = False

    _interactive_prefix    = "\033[0m\033[33m[PYFLYBY]\033[0m "
    _noninteractive_prefix = "[PYFLYBY] "

    def emit(self, record):
        """
        Emit a log record.
        """
        try:
            # Call pre-log hook.
            if self._pre_log_function is not None:
                if not self._logged_anything_during_context:
                    self._pre_log_function()
                    self._logged_anything_during_context = True
            # Format (currently a no-op).
            msg = self.format(record)
            # Add prefix per line.
            if _is_interactive(sys.stderr):
                prefix = self._interactive_prefix
            else:
                prefix = self._noninteractive_prefix
            msg = ''.join(["%s%s\n" % (prefix, line) for line in msg.splitlines()])
            # First, flush stdout, to make sure that stdout and stderr don't get
            # interleaved.  Normally this is automatic, but when stdout is piped,
            # it can be necessary to force a flush to avoid interleaving.
            sys.stdout.flush()
            # Write log message.
            sys.stderr.write(msg)
            # Flush now - we don't want any interleaving of stdout/stderr.
            sys.stderr.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    @contextmanager
    def HookCtx(self, pre, post):
        """
        Enter a context where:
          * C{pre} is called before the first time a log record is emitted
            during the context, and
          * C{post} is called at the end of the context, if any log records
            were emitted during the context.

        @type pre:
          C{callable}
        @param pre:
          Function to call before the first time something is logged during
          this context.
        @type post:
          C{callable}
        @param post:
          Function to call before returning from the context, if anything was
          logged during the context.
        """
        assert self._pre_log_function is None
        self._pre_log_function = pre
        try:
            yield
        finally:
            if self._logged_anything_during_context:
                post()
                self._logged_anything_during_context = False
            self._pre_log_function = None


def _is_interactive(file):
    if type(file).__module__.startswith("IPython."):
        # Inside IPython notebook/kernel
        return True
    try:
        fileno = file.fileno()
    except Exception:
        return False # dunno
    return os.isatty(fileno)


@contextmanager
def _NoRegisterLoggerHandlerInHandlerListCtx():
    """
    Work around a bug in the C{logging} module for Python 2.x-3.2.

    The Python stdlib C{logging} module has a bug where you sometimes get the
    following warning at exit::
      Exception TypeError: "'NoneType' object is not callable" in <function
      _removeHandlerRef at 0x10a1b3f50> ignored

    This is caused by shutdown ordering affecting which globals in the logging
    module are available to the _removeHandlerRef function.

    Python 3.3 fixes this.

    For earlier versions of Python, this context manager works around the
    issue by avoiding registering a handler in the _handlerList.  This means
    that we no longer call "flush()" from the atexit callback.  However, that
    was a no-op anyway, and even if we needed it, we could call it ourselves
    atexit.

    @see:
      U{http://bugs.python.org/issue9501}
    """
    if not hasattr(logging, "_handlerList"):
        yield
        return
    if sys.version_info >= (3, 3):
        yield
        return
    try:
        orig_handlerList = logging._handlerList[:]
        yield
    finally:
        logging._handlerList[:] = orig_handlerList



class PyflybyLogger(Logger):

    _LEVELS = dict( (k, getattr(logging, k))
                    for k in ['DEBUG', 'INFO', 'WARNING', 'ERROR'] )

    def __init__(self, name, level):
        Logger.__init__(self, name)
        with _NoRegisterLoggerHandlerInHandlerListCtx():
            handler = _PyflybyHandler()
        self.addHandler(handler)
        self.set_level(level)

    def set_level(self, level):
        """
        Set the pyflyby logger's level to C{level}.

        @type level:
          C{str}
        """
        if isinstance(level, int):
            level_num = level
        else:
            try:
                level_num = self._LEVELS[level.upper()]
            except KeyError:
                raise ValueError("Bad log level %r" % (level,))
        Logger.setLevel(self, level_num)

    @property
    def debug_enabled(self):
        return self.level <= logging.DEBUG

    @property
    def info_enabled(self):
        return self.level <= logging.INFO

    def HookCtx(self, pre, post):
        return self.handlers[0].HookCtx(pre, post)


logger = PyflybyLogger('pyflyby', os.getenv("PYFLYBY_LOG_LEVEL") or "INFO")
