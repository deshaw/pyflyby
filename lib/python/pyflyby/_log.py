# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



from __future__ import print_function

import builtins
from   contextlib               import nullcontext
import logging
from   logging                  import Formatter, Handler, Logger
import os
from   prompt_toolkit           import patch_stdout
import sys


class _PyflybyFormatter(Formatter):
    _ANSI_RESET = "\033[0m"
    _COLORS = {
        "blue": "\033[34m",
        "yellow": "\033[33m",
        "red": "\033[31m",
    }

    def _color_for_level(self, levelno):
        if levelno >= logging.ERROR:
            return self._COLORS["red"]
        elif levelno >= logging.WARNING:
            return self._COLORS["yellow"]
        else:
            return self._COLORS["blue"]

    def formatInteractive(self, record):
        color = self._color_for_level(record.levelno)
        prefix = "%s%s[PYFLYBY]%s " % (self._ANSI_RESET, color, self._ANSI_RESET)
        msg = super().format(record)
        return "".join(["%s%s\n" % (prefix, line) for line in msg.splitlines()])

    def formatPlain(self, record):
        msg = super().format(record)
        return "".join(["[PYFLYBY] %s\n" % line for line in msg.splitlines()])


class _PyflybyHandler(Handler):

    _pre_log_function = None
    _logged_anything_during_context = False

    def __init__(self):
        super().__init__()
        self.setFormatter(_PyflybyFormatter())

    def emit(self, record):
        try:
            formatter = self.formatter
            if _is_ipython() or _is_interactive(sys.stderr):
                msg = formatter.formatInteractive(record)
                patch_stdout_c = patch_stdout.patch_stdout(raw=True)
            else:
                msg = formatter.formatPlain(record)
                patch_stdout_c = nullcontext()

            with patch_stdout_c:
                sys.stderr.write(msg)
                sys.stderr.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            self.handleError(record)

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
        self.addHandler(_PyflybyHandler())
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


logger = PyflybyLogger('pyflyby', os.getenv("PYFLYBY_LOG_LEVEL") or "INFO")
