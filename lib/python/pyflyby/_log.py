# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

from   contextlib               import contextmanager
import logging
from   logging                  import Formatter, Logger, StreamHandler
import os


class _HookedStreamHandler(StreamHandler):

    _pre_log_function = None
    _logged_anything_during_context = False

    def emit(self, record):
        if self._pre_log_function is not None:
            if not self._logged_anything_during_context:
                self._pre_log_function()
                self._logged_anything_during_context = True
        StreamHandler.emit(self, record)


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
        # Inside IPython notebook
        return True
    try:
        fileno = file.fileno()
    except Exception:
        return False # dunno
    return os.isatty(fileno)



class PyflybyLogger(Logger):

    _LEVELS = dict( (k, getattr(logging, k))
                    for k in ['DEBUG', 'INFO', 'WARNING', 'ERROR'] )

    def __init__(self, name, level):
        Logger.__init__(self, name)
        handler = _HookedStreamHandler()
        if _is_interactive(handler.stream):
            pfx = "\033[0m\033[33m[PYFLYBY]\033[0m"
        else:
            pfx = "[PYFLYBY]"
        formatter = Formatter('{pfx} %(message)s'.format(pfx=pfx))
        handler.setFormatter(formatter)
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

    def HookCtx(self, pre, post):
        return self.handlers[0].HookCtx(pre, post)


logger = PyflybyLogger('pyflyby', os.getenv("PYFLYBY_LOG_LEVEL") or "INFO")
