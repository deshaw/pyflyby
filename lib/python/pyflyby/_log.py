# pyflyby/_log.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



from __future__ import annotations, print_function

import builtins
from   contextlib               import nullcontext
import logging
from   logging                  import Formatter, Handler, LogRecord, Logger
import os
from   prompt_toolkit           import patch_stdout
import sys
from   typing                   import Any, ContextManager, Dict, cast


class _PyflybyFormatter(Formatter):
    _ANSI_RESET = "\033[0m"
    _COLORS: Dict[str, str] = {
        "blue": "\033[34m",
        "yellow": "\033[33m",
        "red": "\033[31m",
    }

    def _color_for_level(self, levelno: int) -> str:
        if levelno >= logging.ERROR:
            return self._COLORS["red"]
        elif levelno >= logging.WARNING:
            return self._COLORS["yellow"]
        else:
            return self._COLORS["blue"]

    def formatInteractive(self, record: LogRecord) -> str:
        color = self._color_for_level(record.levelno)
        prefix = "%s%s[PYFLYBY]%s " % (self._ANSI_RESET, color, self._ANSI_RESET)
        msg = super().format(record)
        return "".join(["%s%s\n" % (prefix, line) for line in msg.splitlines()])

    def formatPlain(self, record: LogRecord) -> str:
        msg = super().format(record)
        return "".join(["[PYFLYBY] %s\n" % line for line in msg.splitlines()])


class _PyflybyHandler(Handler):

    _pre_log_function = None
    _logged_anything_during_context = False

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(_PyflybyFormatter())

    def emit(self, record: LogRecord) -> None:
        try:
            formatter = cast(_PyflybyFormatter, self.formatter)
            if _is_ipython() or _is_interactive(sys.stderr):
                msg = formatter.formatInteractive(record)
                patch_stdout_c: ContextManager[Any] = patch_stdout.patch_stdout(raw=True)
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

def _is_interactive(file: Any) -> bool:
    filemod = type(file).__module__
    if filemod.startswith("IPython.") or filemod.startswith("prompt_toolkit."):
        # Inside IPython notebook/kernel
        return True
    try:
        fileno = file.fileno()
    except Exception:
        return False # dunno
    return os.isatty(fileno)


def _is_ipython() -> bool:
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


def _get_logger() -> Logger:
    """
    Return the ``'pyflyby'`` logger, registered in the standard ``logging``
    hierarchy (so ``logging.getLogger("pyflyby")`` returns the same object).
    """
    logger = logging.getLogger("pyflyby")
    # Guard against adding a second handler if pyflyby is unloaded and
    # re-imported (compare by class name: after a reload, _PyflybyHandler is
    # a new class object).
    if not any(type(h).__name__ == _PyflybyHandler.__name__
               for h in logger.handlers):
        logger.addHandler(_PyflybyHandler())
    logger.setLevel((os.getenv("PYFLYBY_LOG_LEVEL") or "INFO").upper())
    return logger


logger = _get_logger()
