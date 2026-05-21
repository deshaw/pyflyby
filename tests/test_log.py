# pyflyby/test_log.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/


import io
import logging
import sys

import pytest

from   pyflyby._log             import (PyflybyLogger, _PyflybyFormatter,
                                        _is_interactive, logger)


def test_pyflyby_logger_set_level_str():
    log = PyflybyLogger("test1", "INFO")
    log.set_level("DEBUG")
    assert log.level == logging.DEBUG
    log.set_level("info")  # case-insensitive
    assert log.level == logging.INFO
    log.set_level("WARNING")
    assert log.level == logging.WARNING
    log.set_level("ERROR")
    assert log.level == logging.ERROR


def test_pyflyby_logger_set_level_int():
    log = PyflybyLogger("test2", "INFO")
    log.set_level(logging.DEBUG)
    assert log.level == logging.DEBUG


def test_pyflyby_logger_set_level_bad():
    log = PyflybyLogger("test3", "INFO")
    with pytest.raises(ValueError):
        log.set_level("NOPE")


def test_pyflyby_logger_debug_enabled():
    log = PyflybyLogger("test4", "DEBUG")
    assert log.debug_enabled
    assert log.info_enabled
    log.set_level("INFO")
    assert not log.debug_enabled
    assert log.info_enabled
    log.set_level("WARNING")
    assert not log.debug_enabled
    assert not log.info_enabled


def test_pyflyby_logger_construction_default():
    log = PyflybyLogger("test5", "WARNING")
    assert log.name == "test5"
    assert log.level == logging.WARNING


def test_formatter_color_levels():
    f = _PyflybyFormatter()
    assert f._color_for_level(logging.ERROR) == f._COLORS["red"]
    assert f._color_for_level(logging.CRITICAL) == f._COLORS["red"]
    assert f._color_for_level(logging.WARNING) == f._COLORS["yellow"]
    assert f._color_for_level(logging.INFO) == f._COLORS["blue"]
    assert f._color_for_level(logging.DEBUG) == f._COLORS["blue"]


def _make_record(msg, level=logging.INFO):
    return logging.LogRecord(
        name="test", level=level, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )


def test_formatter_format_plain_single_line():
    f = _PyflybyFormatter()
    out = f.formatPlain(_make_record("hello"))
    assert out == "[PYFLYBY] hello\n"


def test_formatter_format_plain_multi_line():
    f = _PyflybyFormatter()
    out = f.formatPlain(_make_record("line1\nline2"))
    assert out == "[PYFLYBY] line1\n[PYFLYBY] line2\n"


def test_formatter_format_interactive_contains_pyflyby():
    f = _PyflybyFormatter()
    out = f.formatInteractive(_make_record("hello"))
    assert "[PYFLYBY]" in out
    assert "hello" in out
    assert out.endswith("\n")


def test_is_interactive_non_tty():
    # StringIO has no fileno
    assert _is_interactive(io.StringIO()) is False


def test_is_interactive_no_fileno():
    class Fake:
        pass
    assert _is_interactive(Fake()) is False


def test_module_logger_exists():
    assert logger.name == "pyflyby"
    assert isinstance(logger, PyflybyLogger)


def test_logger_emits_plain(capsys):
    log = PyflybyLogger("test_emit", "INFO")
    # Force non-interactive path by writing to a pipe-like stream
    old_stderr = sys.stderr
    buf = io.StringIO()
    sys.stderr = buf
    try:
        log.info("hello world")
    finally:
        sys.stderr = old_stderr
    out = buf.getvalue()
    assert "hello world" in out
    assert "[PYFLYBY]" in out
