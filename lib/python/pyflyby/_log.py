# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



import builtins
from   contextlib               import contextmanager
import logging
from   logging                  import Handler, Logger
import os
import sys
from prompt_toolkit import patch_stdout


class _PyflybyHandler(Handler):

    _pre_log_function = None
    _logged_anything_during_context = False

    _interactive_prefix    = "\033[0m\033[33m[PYFLYBY]\033[0m "
    _noninteractive_prefix = "[PYFLYBY] "

    def emit(self, record):
        try:
            if _is_ipython() or _is_interactive(sys.stderr):
                prefix = self._interactive_prefix
            else:
                prefix = self._noninteractive_prefix

            msg = self.format(record)
            msg = ''.join(["%s%s\n" % (prefix, line) for line in msg.splitlines()])
            with patch_stdout.patch_stdout(raw=True):
                sys.stderr.write(msg)
                sys.stderr.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            sys.__stderr__.write(f"AN ERROR OCCURRED {record}")
            self.handleError(record)

    @contextmanager
    def HookCtx(self, pre, post):
        """
        Enter a context where:
          * ``pre`` is called before the first time a log record is emitted
            during the context, and
          * ``post`` is called at the end of the context, if any log records
            were emitted during the context.

        :type pre:
          ``callable``
        :param pre:
          Function to call before the first time something is logged during
          this context.
        :type post:
          ``callable``
        :param post:
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
    filemod = type(file).__module__
    if filemod.startswith("IPython.") or filemod.startswith("prompt_toolkit."):
        # Inside IPython notebook/kernel
        return True
    try:
        fileno = file.fileno()
    except Exception:
        return False # dunno
    return os.isatty(fileno)


def _is_ipython():
    """
    Returns true if we're currently running inside IPython.
    """
    # This currently only works for versions of IPython that are modern enough
    # to install 'builtins.get_ipython()'.
    if 'IPython' not in sys.modules:
        return False
    if not hasattr(builtins, "get_ipython"):
        return False
    ip = builtins.get_ipython()
    if ip is None:
        return False
    return True


class PyflybyLogger(Logger):

    _LEVELS = dict( (k, getattr(logging, k))
                    for k in ['DEBUG', 'INFO', 'WARNING', 'ERROR'] )

    def __init__(self, name, level):
        Logger.__init__(self, name)
        handler = _PyflybyHandler()
        self.addHandler(handler)
        self.set_level(level)

    def set_level(self, level):
        """
        Set the pyflyby logger's level to ``level``.

        :type level:
          ``str``
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

    def log(self, *args, **kwargs):
        sys.__stderr__.write(f"\n----\n{sys.stderr}\n----\n")
        return super().log(*args, **kwargs)

logger = PyflybyLogger('pyflyby', os.getenv("PYFLYBY_LOG_LEVEL") or "INFO")
