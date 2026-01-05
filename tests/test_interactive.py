# pyflyby/test_interactive.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

import difflib
import json
import os
import random
import re
import sys
import time

from   contextlib               import contextmanager
from   io                       import BytesIO
from   shutil                   import rmtree
from   subprocess               import check_call
from   tempfile                 import mkdtemp, mkstemp
from   textwrap                 import dedent

import IPython
import flaky
import pexpect
import pytest
import requests

import pyflyby
from   pyflyby._file            import Filename
from   pyflyby._util            import EnvVarCtx, cached_attribute
from   typing                   import Union

is_free_threaded = (sys.version_info >= (3, 13)) and (sys._is_gil_enabled() is False)


# To debug test_interactive.py itself, set the env var DEBUG_TEST_PYFLYBY.
DEBUG = bool(os.getenv("DEBUG_TEST_PYFLYBY"))
_TESTED_EVALUATION_SETTINGS = ['greedy=True', "evaluation='limited'"]

_env_timeout = os.getenv("PYFLYBYTEST_DEFAULT_TIMEOUT", None)
if _env_timeout is not None:
    DEFAULT_TIMEOUT = float(_env_timeout)
    DEFAULT_TIMEOUT_REQUEST = DEFAULT_TIMEOUT
else:
    DEFAULT_TIMEOUT = -1
    DEFAULT_TIMEOUT_REQUEST = None


if os.getenv("PYFLYBYTEST_NORETRY", None):
    retry = lambda x: x
else:
    retry = flaky.flaky(max_runs=5 if DEFAULT_TIMEOUT < 0 else 1)


def _get_Failed_class():
    import _pytest
    try:
        return _pytest.outcomes.OutcomeException
    except AttributeError:
        return _pytest.runner.Failed
_Failed = _get_Failed_class()

def assert_fail():
    """
    Assert that pytest.fail() is called in the context.  Used to self-test.
    """
    return pytest.raises(_Failed)

@pytest.mark.xfail
def test_failing():
    """
    Making sure that xfails functions.
    """
    assert False


def pytest_generate_tests(metafunc):
    # IPython 4 and earlier only had readline frontend.
    # IPython 5.0 through 5.3 only allow prompt_toolkit.
    # IPython 5.4 through 6.5 defaults to prompt_toolkit, but allows choosing readline.
    # IPython 7+ breaks rlipython (https://github.com/ipython/rlipython/issues/21).
    if 'frontend' in metafunc.fixturenames:
        if _IPYTHON_VERSION >= (7,0):
            metafunc.parametrize('frontend', [            'prompt_toolkit'])
        else:
            raise ImportError("IPython < 8 is unsupported.")


@pytest.fixture
def tmp(request):
    return _TmpFixture(request)

class _TmpFixture(object):
    def __init__(self, request):
        self._request = request

    @cached_attribute
    def dir(self):
        """
        Single memoized new_tempdir()
        """
        return self.new_tempdir()

    @cached_attribute
    def file(self):
        """
        Single memoized new_tempfile().
        The file is NOT under ``self.dir``.
        """
        return self.new_tempfile()

    @cached_attribute
    def ipython_dir(self):
        d = self.new_tempdir()
        _init_ipython_dir(d)
        return d

    def new_tempdir(self):
        d = mkdtemp(prefix="pyflyby_test_", suffix=".tmp")
        self._request.addfinalizer(lambda: rmtree(d))
        return Filename(d)

    def new_tempfile(self, dir=None):
        fd, f = mkstemp(prefix="pyflyby_test_", suffix=".tmp", dir=dir)
        os.close(fd)
        self._request.addfinalizer(lambda: os.unlink(f))
        return Filename(f)


def writetext(filename: Filename, text: str, mode: str = "w") -> Filename:
    assert isinstance(filename, Filename)
    text = dedent(text)
    with open(str(filename), mode) as f:
        f.write(text)
    return filename


def assert_match(result, expected, ignore_prompt_number=False):
    """
    Check that ``result`` matches ``expected``.
    ``expected`` is a pattern where
      * "..." (three dots) matches any text (but not newline), and
      * "...." (four dots) matches any text (including newline).
    """
    __tracebackhide__ = True
    expected = dedent(expected.decode('utf-8')).strip().encode('utf-8')
    parts = expected.split(b"...")
    regexp_parts = [re.escape(parts[0])]
    for s in parts[1:]:
        if re.match(b":( |$)", s, re.M) and regexp_parts[-1] == b"  ":
            # Treat "\n  ...: " specially; don't make it a glob.
            regexp_parts.append(b"...")
            regexp_parts.append(re.escape(s))
        elif s.startswith(b"."):
            regexp_parts.append(b"(?:.|\n)*")
            regexp_parts.append(re.escape(s[1:]))
        else:
            regexp_parts.append(b".*")
            regexp_parts.append(re.escape(s))
    regexp = b"".join(regexp_parts)
    if ignore_prompt_number:
        regexp = re.sub(br"(In\\? |Out)\\*\[[0-9]+\\*\]\\?:", br"\1\[[0-9]+\]:", regexp)
    if _IPYTHON_VERSION >= (4,):
        ignore = dedent(r"""
            (\[ZMQTerminalIPythonApp\] Loading IPython extension: storemagic
            )?
        """).strip().encode('utf-8')
        result = re.sub(ignore, b"", result)

        # ignore self exit on readline.
        result = re.sub(br"In \[\d+\]: exit\(\)", b"", result)

    if _IPYTHON_VERSION < (1, 0):
        assert False, "we don't support IPython pre  1.0 anymore"
        # Ignore the "Compiler time: 0.123 s" which may occasionally appear
    # depending on runtime.
    regexp = re.sub(re.compile(br"^(1[\\]* loops[\\]*,[\\]* best[\\]* of[\\]* 1[\\]*:[\\]* .*[\\]* per[\\]* loop)($|[$]|[\\]*\n)", re.M),
                    b"\\1(?:\nCompiler (?:time)?: [0-9.]+ s)?\\2", regexp)
    regexp = re.sub(re.compile(br"^(Wall[\\]* time[\\]*:.*?)($|[$]|[\\]*\n)", re.M),
                    b"\\1(?:\nCompiler (?:time)?: [0-9.]+ s)?\\2", regexp)
    regexp += b"$"
    # Check for match.
    regexp = re.compile(regexp)
    result = b'\n'.join(line.rstrip() for line in result.splitlines())
    result = result.strip()

    if DEBUG:
        print("expected: %r" % (expected,))
        print("result  : %r" % (result,))
    if not regexp.match(result):
        msg = []
        msg.append("Expected:")
        msg.extend("     %s"%line for line in expected.splitlines())
        msg.append("Result:")
        msg.extend("     %s"%line for line in result.splitlines())
        msg.append("Diff:")
        msg.extend("   %s"%line for line in difflib.ndiff(
            expected.decode('utf-8').splitlines(), result.decode('utf-8').splitlines()))
        if DEBUG or any(i in b'\x1b\x07\b\t' for i in expected+result):
            msg.append("Diff Repr:")
            msg.extend("   %r"%line for line in difflib.ndiff(
                expected.decode('utf-8').splitlines(), result.decode('utf-8').splitlines()))
        msg = "\n".join(msg)
        pytest.fail(msg)


def parse_template(template, clear_tab_completions=False):
    template = dedent(template).strip().encode('utf-8')
    input = []
    expected = b""
    pattern = re.compile(br"^(?:In \[[0-9]+\]:|   [.][.][.]+:|ipdb>|>>>)(?: |$)", re.M)
    while template:
        m = pattern.search(template)
        if not m:
            expected += template
            break
        expline = m.group(0)
        expected += template[:m.end()]
        template = template[m.end():]
        while template and not template.startswith(b"\n"):
            # We're in the input part of a template.  Get input up to tab or
            # end of line.
            m = re.match(re.compile(br"(.*?)(\t|$)", re.M), template)
            input.append(m.group(1))
            expline += m.group(1)
            expected += m.group(1)
            tab = m.group(2)
            template = template[m.end():]
            if not tab:
                break
            # Got a tab.  Include the tab in input to send, but not in
            # expected output.
            input.append(tab)
            # If the template ends a line with a tab, then assume that
            # IPython will output some logging (as included in the
            # template) and repeat the line so far (as included in the
            # template), then possibly tab complete some more.  It might
            # be repeated multiple times, for a total of up to three
            # occurrences of the same prompt.  We find where to continue
            # by looking for the line repeated in the template.
            if template.startswith(b"\n"):
                if clear_tab_completions:
                    # In prompt-toolkit 2.0, tab completion at the end of the line is cleared in the output
                    newline = expected.rfind(b'\n')
                    if newline == -1: newline = 0
                    expected = expected[:newline]

                rep = template.rfind(expline)
                if rep < 0:
                    raise AssertionError(
                        "expected next line of template following a "
                        "tab completion to start with %r" % (expline,))
                repend = rep + len(expline)
                expected += template[:repend]
                template = template[repend:]
            # Assume that all subsequent symbol characters (alphanumeric
            # and underscore) in the template represent tab completion
            # output.
            m = re.match(br"[a-zA-Z0-9_]+", template)
            if m:
                expline += m.group(0)
                expected += m.group(0)
                template = template[m.end():]
                # Allow \x06 in the template to be a special character meaning
                # "end of tab completion output".
            if template.startswith(b"\x06"):
                template = template[1:]
        input.append(b"\n")
    input = b"".join(input)
    return input, expected


@retry
@pytest.mark.parametrize('clear_tab_completions', [False, True])
def test_selftest_parse_template_1(clear_tab_completions):
    template = """
        In [1]: hello
        there
        world
        In [2]: foo
           ...: bar
           ...:
        baz
    """
    input, expected = parse_template(template, clear_tab_completions=clear_tab_completions)
    assert input == b"hello\nfoo\nbar\n\n"
    assert expected == (
        b"In [1]: hello\nthere\nworld\n"
        b"In [2]: foo\n   ...: bar\n   ...:\nbaz")


@retry
@pytest.mark.parametrize('clear_tab_completions', [False, True])
def test_selftest_parse_template_tab_punctuation_1(clear_tab_completions):
    template = """
        In [1]: hello\t_there(3)
        goodbye
    """
    input, expected = parse_template(template, clear_tab_completions=clear_tab_completions)
    assert input == b"hello\t(3)\n"
    assert expected == (b"In [1]: hello_there(3)\ngoodbye")


@retry
@pytest.mark.parametrize('clear_tab_completions', [False, True])
def test_selftest_parse_template_tab_newline_(clear_tab_completions):
    template = """
        In [1]: hello_\tthere
        goodbye
    """
    input, expected = parse_template(template, clear_tab_completions=clear_tab_completions)
    assert input == b"hello_\t\n"
    assert expected == (b"In [1]: hello_there\ngoodbye")


@retry
@pytest.mark.parametrize('clear_tab_completions', [False, True])
def test_selftest_parse_template_tab_continue_1(clear_tab_completions):
    template = """
        In [1]: hello\t_the\x06re(3)
        goodbye
    """
    input, expected = parse_template(template)
    assert input == b"hello\tre(3)\n"
    assert expected == (b"In [1]: hello_there(3)\ngoodbye")


@retry
@pytest.mark.parametrize('clear_tab_completions', [False, True])
def test_selftest_parse_template_tab_log_1(clear_tab_completions):
    template = """
        In [1]: hello\t
        bonjour
        In [1]: hello
        hallo
        In [1]: hello_there(5)
        goodbye
    """
    input, expected = parse_template(template, clear_tab_completions=clear_tab_completions)
    assert input == b"hello\t(5)\n"
    if clear_tab_completions:
        assert expected == (
            b"\n"
            b"bonjour\n"
            b"In [1]: hello\n"
            b"hallo\n"
            b"In [1]: hello_there(5)\n"
            b"goodbye")
    else:
        assert expected == (
            b"In [1]: hello\n"
            b"bonjour\n"
            b"In [1]: hello\n"
            b"hallo\n"
            b"In [1]: hello_there(5)\n"
            b"goodbye")


@retry
def test_selftest_assert_match_1():
    expected = b"""
        hello
        1...2
        goodbye
        ....hello
    """
    result = dedent("""

      hello
      14712047602
      goodbye
      I don't know why you say goodbye
      I say hello
    """).encode('utf-8')
    assert_match(result, expected)


@retry
def test_selftest_assert_match_2():
    result = b"""
        hello
        1...2
        there
    """
    expected = b"""

      hello
      14712047
      602
      there

    """
    with assert_fail():
        assert_match(result, expected)


@retry
def test_lazy_import_ipython_1():
    # Verify that "import pyflyby" doesn't imply "import IPython".
    pycmd = 'import pyflyby, sys; sys.exit("IPython" in sys.modules)'
    check_call(["python", "-c", pycmd])


def _parse_version(version_string):
    """
      >>> _parse_version("1.2.3")
      (1, 2, 3)

      >>> _parse_version("1.2a.3b")
      (1, 2, 'a', 3, 'b')
    """
    result = []
    for part in version_string.split("."):
        m = re.match("^([0-9]*)(.*)$", part)
        if m.group(1):
            result.append(int(m.group(1)))
        if m.group(2):
            result.append(m.group(2))
    return tuple(result)


try:
    _IPYTHON_VERSION = IPython.version_info
except AttributeError:
    _IPYTHON_VERSION = _parse_version(IPython.__version__)


# `policy_overrides` and `auto_import_method` were added in IPython 9.3
_SUPPORTS_TAB_AUTO_IMPORT = _IPYTHON_VERSION < (9, 3)

# Prompts that we expect for.
_IPYTHON_PROMPT1 = br"\n\r?In \[([0-9]+)\]: "
_IPYTHON_PROMPT2 = br"\n\r?   [.][.][.]+: "
_PYTHON_PROMPT = br">>> "
_IPDB_PROMPT = br"\nipdb> "
_IPYTHON_PROMPTS = [_IPYTHON_PROMPT1,
                    _IPYTHON_PROMPT2,
                    _PYTHON_PROMPT,
                    _IPDB_PROMPT]
# Currently _interact_ipython() assumes the first is "In [nn]:"
assert b"In " in _IPYTHON_PROMPTS[0]


def _build_pythonpath(PYTHONPATH) -> str:
    """
    Build PYTHONPATH value to use.

    :rtype:
      ``str``
    """
    pypath = [os.path.dirname(os.path.dirname(pyflyby.__file__))]
    if isinstance(PYTHONPATH, Filename):
        PYTHONPATH = [str(PYTHONPATH)]
    if isinstance(PYTHONPATH, str):
        PYTHONPATH = [PYTHONPATH]
    for p in PYTHONPATH:
        assert isinstance(p, str)
    PYTHONPATH = [str(Filename(d)) for d in PYTHONPATH]
    pypath += PYTHONPATH
    pypath += os.environ["PYTHONPATH"].split(":")
    return ":".join(pypath)


def _init_ipython_dir(ipython_dir: Union[Filename, str]):
    if isinstance(ipython_dir, str):
        ipython_dir = Filename(ipython_dir)
    assert isinstance(ipython_dir, Filename)
    if _IPYTHON_VERSION >= (0, 11):
        os.makedirs(str(ipython_dir/"profile_default"))
        os.makedirs(str(ipython_dir/"profile_default/startup"))
        if _IPYTHON_VERSION >= (7,):
            writetext(ipython_dir/"profile_default/ipython_config.py",
                  dedent("""
                  c = get_config()
                  # Prompt-toolkit 2.0 still prints some escape codes for the
                  # completion display even if there is only one completion.
                  c.TerminalInteractiveShell.display_completions = "readlinelike"
                  c.TerminalInteractiveShell.colors = 'NoColor'
                  # Disable bracket highlighting, which prints escape codes that confuse the decoder.
                  c.TerminalInteractiveShell.highlight_matching_brackets = False
                  """))
            writetext(ipython_dir/"jupyter_console_config.py",
                  dedent("""
                  c = get_config()
                  # Disable bracket highlighting, which prints escape codes that confuse the decoder.
                  c.ZMQTerminalInteractiveShell.display_completions = "readlinelike"
                  # Not supported in Jupyter console
                  # c.ZMQTerminalInteractiveShell.colors = 'NoColor'
                  # Prompt-toolkit 2.0 still prints some escape codes for the
                  # completion display even if there is only one completion.
                  c.ZMQTerminalInteractiveShell.highlight_matching_brackets = False
                  """))
        elif _IPYTHON_VERSION >= (5,):
            writetext(ipython_dir/"profile_default/ipython_config.py",
                  dedent("""
                  c = get_config()
                  c.TerminalInteractiveShell.colors = 'NoColor'
                  # Prompt-toolkit 2.0 still prints some escape codes for the
                  # completion display even if there is only one completion.
                  c.TerminalInteractiveShell.highlight_matching_brackets = False
                  """))
        else:
            writetext(ipython_dir/"profile_default/ipython_config.py",
                  "c = get_config()\n")
    elif _IPYTHON_VERSION >= (0, 10):
        writetext(ipython_dir/"ipythonrc", """
            readline_parse_and_bind tab: complete
            readline_parse_and_bind set show-all-if-ambiguous on
        """)
        writetext(ipython_dir/"ipy_user_conf.py", "")


def _build_ipython_cmd(
    ipython_dir: Filename, prog="ipython", args=[], autocall=False, frontend=None
):
    """
    Prepare the command to run IPython.
    """
    python = sys.executable
    assert isinstance(ipython_dir, Filename)
    cmd = [python]
    if prog == "ipython" and _IPYTHON_VERSION >= (4,) and args and args[0] in ["console", "notebook"]:
        prog = "jupyter"
    if prog == "py":
        cmd += [str(PYFLYBY_BIN / prog)]
    else:
        # Get the program from the python that is running.
        cmd += [os.path.join(os.path.dirname(sys.executable), prog)]
    if isinstance(args, str):
        args = [args]
    if args and not args[0].startswith("-"):
        app = args[0]
    else:
        app = "terminal"
    cmd += list(args)
    if prog == "python":
        return cmd
    # Construct IPython arguments based on version.
    if _IPYTHON_VERSION >= (0, 11):
        opt = lambda arg: arg
    elif _IPYTHON_VERSION >= (0, 10):
        def opt(arg):
            """
              >>> opt('--foo-bar=x-y')
              '-foo_bar=x-y'
            """
            m = re.match("--([^=]+?)(=.*)?$", arg)
            optname = m.group(1)
            optval  = m.group(2) or ""
            optname = re.sub("^no-", "no", optname)
            optname = re.sub("-", "_", optname)
            optname = re.sub("^ipython_dir$", "ipythondir", optname)
            return "-%s%s" % (optname, optval)
    else:
        raise NotImplementedError("Don't know how to test IPython version %s"
                                  % (_IPYTHON_VERSION,))
    cmd = ['env', 'IPYTHONDIR=%s' % (ipython_dir,), 'JUPYTER_CONFIG_DIR=%s' % (ipython_dir,), 'INPUTRC=none', 'PROMPT_TOOLKIT_NO_CPR=1'] + cmd
    if app == "terminal" and prog != "py":
        cmd += [opt("--no-confirm-exit")]
        cmd += [opt("--no-banner")]
    if app == "console" and prog != "py":
        cmd += [opt("--no-confirm-exit")]
        if _IPYTHON_VERSION < (4,):
            cmd += [opt("--no-banner")]
    if app != "notebook" and prog != "py":
        cmd += [opt("--colors=NoColor")]
    if frontend == 'prompt_toolkit' and _IPYTHON_VERSION < (7,) or prog == "py":
        # prompt_toolkit (IPython 5) doesn't support turning off autoindent.  It
        # has various command-line options which toggle the internal
        # shell.autoindent flag, but turning that internal flag off doesn't do
        # anything.  Instead we'll just have to send a ^U at the beginning of
        # each line to defeat the autoindent. The feature was re-enabled in
        # IPython 7, so we don't need to worry there.
        pass
    elif _IPYTHON_VERSION >= (3,):
        cmd += ["--InteractiveShell.autoindent=False"]
    else:
        cmd += [opt("--no-autoindent")]
    if autocall:
        if _IPYTHON_VERSION >= (3,0):
            cmd += ["--InteractiveShell.autocall=True"]
        else:
            cmd += [opt("--autocall=1")]
    if frontend == 'readline':
        if _IPYTHON_VERSION < (8, 0):
            raise ValueError("IPython < 8 is unsupported.")
    elif frontend == 'prompt_toolkit':
        if _IPYTHON_VERSION >= (5,):
            # For IPython >= 5.0, prompt_toolkit is the default option (and
            # for 5.0-5.3, the only option).
            pass
        else:
            raise ValueError("IPython 4 and earlier only support readline")
    else:
        raise ValueError("bad frontend=%r" % (frontend,))
    return cmd


PYFLYBY_HOME = Filename(__file__).real.dir.dir
PYFLYBY_PATH = PYFLYBY_HOME / "etc/pyflyby"
PYFLYBY_BIN = PYFLYBY_HOME / "bin"

class AnsiFilterDecoder(object):
    # TODO: replace this with `pyte`?

    def __init__(self):
        self._buffer = b""

    def decode(self, arg, final=False):
        arg0 = arg = self._buffer + arg
        self._buffer = b""
        arg = re.sub(b"\r+\n", b"\n", arg)
        arg = arg.replace(b"\x1b[J", b"")             # clear to end of display
        arg = re.sub(br"\x1b\[[0-9]+(?:;[0-9]+)*m", b"", arg) # color
        arg = re.sub(br"([^\n])(\[PYFLYBY\])", br"\1\n\2", arg) # ensure [PYFLYBY] goes on its own line
        arg = arg.replace(b"\x1b[6n", b"")            # query cursor position
        arg = arg.replace(b"\x1b[?1l", b"")           # normal cursor keys
        arg = arg.replace(b"\x1b[?7l", b"")           # no wraparound mode
        arg = arg.replace(b"\x1b[?12l", b"")          # stop blinking cursor
        arg = arg.replace(b"\x1b[?25l", b"")          # hide cursor
        arg = arg.replace(b"\x1b[?2004l", b"")        # no bracketed paste mode
        arg = arg.replace(b"\x1b[?7h", b"")           # wraparound mode
        arg = arg.replace(b"\x1b[?25h", b"")          # show cursor
        arg = arg.replace(b"\x1b[23;0t", b"")          # restore window title
        arg = arg.replace(b"\x1b[?2004h", b"")        # bracketed paste mode
        arg = arg.replace(b'\x1b[?5h\x1b[?5l', b'')   # visual bell
        arg = re.sub(br"\x1b\[([0-9]+)D\x1b\[\1C", b"", arg) # left8,right8 no-op (srsly?)
        arg = arg.replace(b'\x1b[?1034h', b'')        # meta key
        arg = arg.replace(b'\x1b[A', b'')             # move the cursor up one line
        arg = arg.replace(b'\x1b>', b'')              # keypad numeric mode (???)
        arg = arg.replace(b'?[33m', b'')              # yellow text
        arg = arg.replace(b'?[0m', b'')              # reset (no more yellow)

        # cursor movement on PTK 3.0.6+ compute the number of back and forth and
        # insert that many spaces.
        pat = br"\x1b\[(\d+)D\x1b\[(\d+)C"
        match = re.search(pat, arg)

        while match:
            backward, forward = match.groups()
            backward, forward = int(backward), int(forward)
            n_spaces = forward - backward
            start, stop = match.start(), match.end()
            arg = arg[:start]+n_spaces*b' '+arg[stop:]
            match = re.search(pat, arg)

        arg = re.sub(br"\n\x1b\[[0-9]*C", b"", arg) # move cursor right immediately after a newline
        # Cursor movement. We assume this is used only for places that have '...'
        # in the tests.
        # arg = re.sub(b"\\\x1b\\[\\?1049h.*\\\x1b\\[\\?1049l", b"", arg)

        # Assume ESC[5Dabcd\n is rewriting previous text; delete it. Only do
        # so if the line does NOT have '[PYFLYBY]' or a CPR request warning.
        # TODO: find a less hacky way to handle this without hardcoding
        # '[PYFLYBY]'.
        left = b""
        right = arg
        while right:
            m = re.search(br"\x1b\[[0-9]+D.*?\n", right)
            if not m:
                break
            if b'[PYFLYBY]' in m.group() or b'WARNING' in m.group():
                left += right[:m.end()]
            else:
                left += right[:m.start()] + b'\n'
            right = right[m.end():]
        arg = left + right
        # Assume ESC[3A\nline1\nline2\nline3\n is rewriting previous text;
        # delete it.
        left = b""
        right = arg
        while right:
            m = re.search(br"\x1b\[([0-9]+)A\n", right)
            if not m:
                break
            num = int(m.group(1))
            end = m.end()
            suffix = right[end:]
            # splitlines includes \r as a line delimiter, which we do not want
            suffix_lines = suffix.split(b'\n')
            left = left + right[:m.start()]
            if len(suffix_lines) <= num:
                self._buffer += right[m.start():]
                right = b""
                break
            right = b'\n'.join(suffix_lines[num:])
            if suffix.endswith(b'\n'):
                right += b'\n'
        arg = left + right

        # \rESC[5C moves the cursor to the beginning of the line, then right 5
        # characters. Assume anything after any of these is not printed
        # (should be only space and invisible characters). Everything replaced
        # above is zero width, so we can safely do this last.
        lines = []
        for line in arg.split(b'\n'):
            n = len(line)
            m = None
            for m in re.finditer(br'\r\x1b\[([0-9]+)C', line):
                n = int(m.group(1))
            if n > len(line):
                self._buffer += arg
                arg = b""
                break
            elif m and b'\x1b' in line[m.end():]:
                # Some escape code was only seen partially and hence wasn't
                # replaced above. If we cleared it now, the remainder would be
                # shown as plain text in the next arg.
                self._buffer += arg
                arg = b""
                break
            else:
                lines.append(line[:n])
        else:
            arg = b'\n'.join(lines)

        if arg.endswith(b' '*10):
            # Probably going to have some \rESC[5C type clearing. There can be
            # 9 spaces from a double indentation after ...: (currently the
            # most indentation used), but the clearing generally uses hundreds
            # of spaces, so this should distinguish them.
            self._buffer += arg
            arg = b""


        # Uncompleted escape sequence at the end of the string
        if re.search(br"\x1b[^a-zA-Z]*$", arg):
            self._buffer += arg
            arg = b""

        if DEBUG:
            if self._buffer:
                print("AnsiFilterDecoder: %r => %r, pending: %r" % (arg0,arg,self._buffer))
            elif arg != arg0:
                print("AnsiFilterDecoder: %r => %r" % (arg0,arg))
            else:
                print("AnsiFilterDecoder: %r [no change]" % (arg,))
        return arg

class MySpawn(pexpect.spawn):

    def __init__(self, *args, **kwargs):
        super(MySpawn, self).__init__(*args, **kwargs)
        # Filter out various ansi nonsense.  Override self._decoder.  This is
        # called by pexpect.spawnbase.SpawnBase.read_nonblocking.  This is
        # normally initialized by SpawnBase.__init__ intended for unicode
        # decoding.  This is a bit hacky because it's an internal thing that
        # could change.
        self._decoder = AnsiFilterDecoder()
        self.str_last_chars = 1000

    def send(self, arg):
        if DEBUG:
            print("MySpawn.send(%r)" % (arg,))
        return super(MySpawn, self).send(arg)


    def expect(self, arg, timeout=DEFAULT_TIMEOUT):
        if DEBUG:
            print("MySpawn.expect(%r)" % (arg,))
        return super(MySpawn, self).expect(arg, timeout=timeout)


    def expect_exact(self, arg, timeout=DEFAULT_TIMEOUT):
        if DEBUG:
            print("MySpawn.expect_exact(%r)" % (arg,))
        return super(MySpawn, self).expect_exact(arg, timeout=timeout)



class ExpectError(Exception):
    def __init__(self, e, child):
        self.e = e
        self.child = child
        self.args = (e, child)

    def __str__(self):
        return "%s in %s" % (
            self.e.__class__.__name__, ' '.join(self.child.args))


@contextmanager
def IPythonCtx(prog="ipython",
               args=[],
               autocall=False,
               frontend=None,
               ipython_dir=None,
               PYTHONPATH=[],
               PYFLYBY_PATH=PYFLYBY_PATH,
               PYFLYBY_LOG_LEVEL=""):
    """
    Spawn IPython in a pty subprocess.  Send it input and expect output.

    :param frontend:
      Which terminal frontend to use: readline (default for IPython <5) or
      prompt_toolkit (default for IPython >=5).
      IPython 4 and earlier only support readline.
      IPython 5.0 through 5.3 only support prompt_toolkit.
      IPython 5.4 and later support both readline and prompt_toolkit.
    """
    __tracebackhide__ = True
    if hasattr(PYFLYBY_PATH, "write"):
        PYFLYBY_PATH = PYFLYBY_PATH.name
    assert isinstance(PYFLYBY_PATH, Filename)
    PYFLYBY_PATH = str(PYFLYBY_PATH)
    cleanup_dirs = []
    # Create a temporary directory which we'll use as our IPYTHONDIR.
    if not ipython_dir:
        ipython_dir = mkdtemp(prefix="pyflyby_test_ipython_", suffix=".tmp")
        _init_ipython_dir(ipython_dir)
        cleanup_dirs.append(ipython_dir)
    # Create an empty directory for MPLCONFIGDIR to avoid matplotlib looking
    # in $HOME.
    mplconfigdir = mkdtemp(prefix="pyflyby_test_matplotlib_", suffix=".tmp")
    cleanup_dirs.append(mplconfigdir)
    # Figure out frontend to use.
    frontend = _interpret_frontend_arg(frontend)
    child = None
    output = BytesIO()
    try:
        # Prepare environment variables.
        env = {}
        env["PYFLYBY_SUPPRESS_CACHE_REBUILD_LOGS"] = "1"
        env["PYFLYBY_PATH"]      = PYFLYBY_PATH
        env["PYFLYBY_LOG_LEVEL"] = PYFLYBY_LOG_LEVEL
        env["PYTHONPATH"] = _build_pythonpath(PYTHONPATH)
        env["PYTHONSTARTUP"] = ""
        env["MPLCONFIGDIR"] = mplconfigdir
        env["PATH"] = str(PYFLYBY_BIN.real) + os.path.pathsep + os.environ["PATH"]
        env["PYTHONBREAKPOINT"] = "IPython.terminal.debugger.set_trace"
        if isinstance(ipython_dir, str):
            ipython_dir = Filename(ipython_dir)
        cmd = _build_ipython_cmd(
            ipython_dir, prog, args, autocall=autocall, frontend=frontend
        )
        # Spawn IPython.
        with EnvVarCtx(**env):
            print("# Spawning: %s" % (" ".join(cmd)))
            child = MySpawn(
                cmd[0], cmd[1:], echo=True, dimensions=(100, 900), timeout=10.0
            )
        # Record frontend for others.
        child.ipython_frontend = frontend
        # Log output to a BytesIO.  Note that we use "logfile_read", not
        # "logfile".  If we used logfile, that would double-log the input
        # commands, since we used echo=True.  (Using logfile=BytesIO and
        # echo=False works for most inputs, but doesn't work for things like
        # tab completion output.)
        child.logfile_read = output
        # Don't delay 0.05s before sending.
        child.delaybeforesend = 0.0
        # Yield control to caller.
        child.ipython_dir = ipython_dir
        yield child
    except (pexpect.ExceptionPexpect) as e:
        print("Error: %s" % (e.__class__.__name__,))
        print("Output so far:")
        result = _clean_ipython_output(output.getvalue())
        print(''.join("    %s\n"%line for line in result.splitlines()))
        print("Error details:")
        print(''.join("    %s\n"%line for line in str(e).splitlines()))
        # Re-raise an exception wrapped so that we don't re-catch it for the
        # wrong child.
        raise ExpectError(e, child) #, None, sys.exc_info()[2]
    finally:
        # Clean up.
        if child is not None:
            child.close(force=True)
        for d in cleanup_dirs:
            rmtree(d)


def _interact_ipython(child, input, exitstr=b"exit()\n",
                      sendeof=False, waiteof=True):
    is_prompt_toolkit = child.ipython_frontend == "prompt_toolkit"
    # Canonicalize input lines.
    input = dedent(input.decode('utf-8')).encode('utf-8')
    input = re.sub(br"^\n+", b"", input)
    input = re.sub(br"\n+$", b"", input)
    input += b"\n"
    input += exitstr
    lines = input.splitlines(False)
    prev_prompt_in_idx = None
    # Loop over lines.
    for line in lines:
        # Wait for the "In [N]:" prompt.
        while True:
            expect_result = child.expect(_IPYTHON_PROMPTS, timeout=DEFAULT_TIMEOUT)
            if expect_result == 0:
                # We got "In [N]:".
                # Check if we got the same prompt as before.  If so then keep
                # looking for the next prompt.
                in_idx = child.match.group(1)
                if in_idx == prev_prompt_in_idx:
                    # This is still the same In[N] that we previously saw.
                    continue
                prev_prompt_in_idx = in_idx
                break
            else:
                # We got ">>>", "...:", "ipdb>", etc.
                if is_prompt_toolkit:
                    # prompt_toolkit might rewrite "ipdb>" etc multiple times.
                    # Make sure we eat up all the output so that the next
                    # expect("ipdb>") doesn't get the rewritten "ipdb>" from
                    # the previous line.  For "In [N]", we can rely on the
                    # counter to do that.  For prompts without a counter, we
                    # just try our best to eat up pending output.  Todo:
                    # is there a better way?
                    _wait_for_output(child, timeout=0.05)
                break
        while line:
            left, tab, right = line.partition(b"\t")
            # if DEBUG:
            #     print("_interact_ipython(): line=%r, left=%r, tab=%r, right=%r" % (line, left, tab, right))
            # Send the input (up to tab or newline).
            child.send(left)
            # Check that the client IPython gets the input.
            child.expect_exact(left, timeout=DEFAULT_TIMEOUT)
            if tab:
                # Send the tab.
                child.send(tab)
                # Wait for response to tab.
                if is_prompt_toolkit:
                    # When using prompt_toolkit (default for IPython 5+), we
                    # need to wait for output.
                    _wait_for_output(child, timeout=1.0)
                else:
                    # When using readline (only option for IPython 4 and
                    # earlier), we can use the nonce trick.
                    _wait_nonce(child)
            line = right
        child.send(b"\n")
    # We're finished sending input commands.  Wait for process to complete.
    if sendeof:
        child.sendeof()
    if waiteof:
        child.expect(pexpect.EOF, timeout=DEFAULT_TIMEOUT)
    else:
        child.expect(_IPYTHON_PROMPTS, timeout=DEFAULT_TIMEOUT)
    # Get output.
    output = child.logfile_read
    result = output.getvalue()
    result = _clean_ipython_output(result)
    return result


def _interpret_frontend_arg(frontend):
    if frontend is None:
        if _IPYTHON_VERSION >= (5,0):
            frontend = "prompt_toolkit"
        else:
            # IPython 4 and earlier only support readline.
            frontend = "readline"
    if frontend not in ["readline", "prompt_toolkit"]:
        raise ValueError("bad frontend=%r" % (frontend,))
    return frontend


def ipython(template, **kwargs):
    """
    Run IPython in a pty subprocess.  Send it input and expect output based on
    the template.  Assert that the result matches.
    """
    __tracebackhide__ = True
    template = template.replace("... in ...", "... line ...")
    template = dedent(template).strip()
    input, expected = parse_template(template, clear_tab_completions=_IPYTHON_VERSION>=(7,))
    args = kwargs.pop("args", ())
    if isinstance(args, str):
        args = [args]
    args = list(args)
    if args and not args[0].startswith("-"):
        app = args[0]
    else:
        app = "terminal"
    kernel = kwargs.pop("kernel", None)
    if app == "console":
        if kernel is not None:
            if _IPYTHON_VERSION >= (3,2):
                # IPython console 3.2+ kills the kernel upon exit, unless you
                # explicitly ask to keep it open.  If we're connecting to an
                # existing kernel, default to keeping it alive upon exit.
                kwargs.setdefault("exitstr", b"exit(keep_kernel=True)\n")
                kwargs.setdefault("sendeof", False)
            elif _IPYTHON_VERSION >= (3,):
                # IPython console 3.0, 3.1 always kill the kernel upon exit.
                # There's a purported option exit(keep_kernel=True) but it's not
                # implemented in these versions.
                # https://github.com/ipython/ipython/issues/8482
                # https://github.com/ipython/ipython/pull/8483
                # Instead of cleanly telling the client to exit, we'll just kill
                # it with SIGKILL (in the 'finally' clause of IPythonCtx).
                kwargs.setdefault("exitstr", b"")
                kwargs.setdefault("sendeof", False)
                kwargs.setdefault("waiteof", False)
            else:
                kwargs.setdefault("sendeof", True)
                kwargs.setdefault("exitstr", b"" if kwargs['sendeof'] else b"exit()")
        else:
            if _IPYTHON_VERSION >= (5,):
                kwargs.setdefault("sendeof", False)
            else:
                kwargs.setdefault("sendeof", True)
            kwargs.setdefault("exitstr", b"" if kwargs['sendeof'] else b"exit()")
        kwargs.setdefault("ignore_prompt_number", True)
    exitstr              = kwargs.pop("exitstr"             , b"exit()\n")
    sendeof              = kwargs.pop("sendeof"             , False)
    waiteof              = kwargs.pop("waiteof"             , True)
    ignore_prompt_number = kwargs.pop("ignore_prompt_number", False)
    if kernel is not None:
        args += [i.decode('utf-8') for i in kernel.kernel_info]
        kwargs.setdefault("ipython_dir", kernel.ipython_dir)
    print("Input:")
    print("".join("    %s\n"%line for line in input.splitlines()))
    with IPythonCtx(args=args, **kwargs) as child:
        result = _interact_ipython(child, input, exitstr=exitstr,
                                   sendeof=sendeof, waiteof=waiteof)
    print("Output:")
    print("".join("    %s\n"%line for line in result.splitlines()))
    assert_match(result, expected, ignore_prompt_number=ignore_prompt_number)


@contextmanager
def IPythonKernelCtx(**kwargs):
    """
    Launch IPython kernel.
    """
    __tracebackhide__ = True
    with IPythonCtx(args='kernel', **kwargs) as child:
        # Get the kernel info: --existing kernel-1234.json
        child.expect(
            r"To connect another client to this kernel, use:\s*"
            r"(?:\[IPKernelApp\])?\s*(--existing .*?json)",
            timeout=DEFAULT_TIMEOUT,
        )
        kernel_info = child.match.group(1).split()
        # Yield control to caller.
        child.kernel_info = kernel_info
        yield child


def rand_chars(length=8, letters='abcdefghijklmnopqrstuvwxyz'):
    return ''.join([random.choice(letters) for _ in range(length)])



@contextmanager
def IPythonNotebookCtx(**kwargs):
    """
    Launch IPython Notebook.
    """
    __tracebackhide__ = True
    args = kwargs.pop("args", [])
    args = args + ['notebook', '--no-browser', '--ip=127.0.0.1']
    if _IPYTHON_VERSION < (5,):
        passwd_plaintext = rand_chars()
        passwd_hashed = IPython.lib.passwd(passwd_plaintext)
        args += ['--NotebookApp.password=%s' % passwd_hashed]
    notebook_dir = kwargs.pop("notebook_dir", None)
    cleanups = []
    if not notebook_dir:
        notebook_dir = mkdtemp(prefix="pyflyby_test_notebooks_", suffix=".tmp")
        cleanups.append(lambda: rmtree(notebook_dir))
    try:
        args += ['--notebook-dir=%s' % notebook_dir]
        with IPythonCtx(args=args, **kwargs) as child:
            if _IPYTHON_VERSION >= (5,):
                # Get the base URL from the notebook app.
                child.expect(
                    r"\s*(http://[0-9.:]+)/[?]token=([0-9a-f]+)\n",
                    timeout=DEFAULT_TIMEOUT,
                )
                baseurl = child.match.group(1).decode("utf-8")
                token = child.match.group(2)
                params = dict(token=token)
                response = requests.post(
                    baseurl + "/api/contents",
                    params=params,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                assert response.status_code == 201
                # Get the notebook path & name for the new notebook.
                text = response.text
                response_data = json.loads(text)
                path = response_data['path']
                name = response_data['name']
                # Create a session & kernel for the new notebook.
                request_data = json.dumps(dict(notebook=dict(path=path, name=name)))
                response = requests.post(
                    baseurl + "/api/sessions",
                    data=request_data,
                    params=params,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                assert response.status_code == 201
                # Get the kernel_id for the new kernel.
                text = response.text
                response_data = json.loads(text)
                kernel_id = response_data['kernel']['id']
            elif _IPYTHON_VERSION >= (2,):
                # Get the base URL from the notebook app.
                child.expect(
                    r"The (?:IPython|Jupyter) Notebook is running at: (http://[A-Za-z0-9:.]+)[/\r\n]",
                    timeout=DEFAULT_TIMEOUT,
                )
                baseurl = child.match.group(1).decode("utf-8")
                # Login.
                response = requests.post(
                    baseurl + "/login",
                    data=dict(password=passwd_plaintext),
                    allow_redirects=False,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                assert response.status_code == 302
                cookies = response.cookies
                # Create a new notebook.
                # Get notebooks.
                response = requests.post(
                    baseurl + "/api/notebooks",
                    cookies=cookies,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                expected = 200 if _IPYTHON_VERSION >= (3,) else 201
                assert response.status_code == expected
                # Get the notebook path & name for the new notebook.
                text = response.text
                response_data = json.loads(text)
                path = response_data['path']
                name = response_data['name']
                # Create a session & kernel for the new notebook.
                request_data = json.dumps(dict(notebook=dict(path=path, name=name)))
                response = requests.post(
                    baseurl + "/api/sessions",
                    data=request_data,
                    cookies=cookies,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                assert response.status_code == 201
                # Get the kernel_id for the new kernel.
                text = response.text
                response_data = json.loads(text)
                kernel_id = response_data['kernel']['id']
            elif _IPYTHON_VERSION >= (0, 12):
                # Get the base URL from the notebook app.
                child.expect(
                    r"The (?:IPython|Jupyter) Notebook is running at: (http://[A-Za-z0-9:.]+)[/\r\n]",
                    timeout=DEFAULT_TIMEOUT,
                )
                baseurl = child.match.group(1).decode("utf-8")
                # Login.
                response = requests.post(
                    baseurl + "/login",
                    data=dict(password=passwd_plaintext),
                    allow_redirects=False,
                    timeout=DEFAULT_TIMEOUT,
                )
                assert response.status_code == 302
                cookies = response.cookies
                # Create a new notebook.
                response = requests.get(baseurl + "/new")
                assert response.status_code == 200
                # Get the notebook_id for the new notebook.
                text = response.text
                m = re.search(r"data-notebook-id\s*=\s*([0-9a-f-]+)", text)
                assert m is not None
                notebook_id = m.group(1)
                # Start a kernel for the notebook.
                response = requests.post(
                    baseurl + "/kernels?notebook=" + notebook_id,
                    timeout=DEFAULT_TIMEOUT_REQUEST,
                )
                assert response.status_code == 200
                # Get the kernel_id for the new kernel.
                text = response.text
                kernel_id = json.loads(text)['kernel_id']
            else:
                raise NotImplementedError(
                    "Not implemented for IPython %s" % (IPython.__version__))
            # Construct the kernel info line: --existing kernel-123-abcd-...456.json
            kernel_info = [b'--existing', b"kernel-%s.json" % kernel_id.encode('utf-8')]
            # Yield control to caller.
            child.kernel_info = kernel_info
            yield child
    finally:
        for cleanup in cleanups:
            cleanup()


def _wait_for_output(child, timeout):
    """
    Wait up to ``timeout`` seconds for output.
    """
    # In IPython 5, we cannot send any output before IPython responds to the
    # tab, else it won't respond to the tab.  The purpose of this function is
    # to wait for IPython to respond to a tab.
    if DEBUG:
        print("_wait_for_output()")
    got_data_already = False
    # Read ``BLOCKSIZE`` bytes at a time.  Note that currently our ansi filter
    # won't work across block boundaries, so currently this blocksize needs to
    # be large enough that we don't span an ANSI sequence across two blocks.
    BLOCKSIZE = 16*4096
    deadline = time.time() + timeout
    while True:
        if child.flag_eof:
            break
        if got_data_already:
            # If we previously got any data (after ansi filtering), then keep
            # going while there's pending data.
            remaining_timeout = timeout
        else:
            # Wait until timeout.  This condition applies if it's the first
            # loop, or if we've gotten some non-empty data after ansi
            # filtering.
            remaining_timeout = deadline - time.time()
        try:
            data = child.read_nonblocking(BLOCKSIZE, timeout=remaining_timeout)
        except pexpect.TIMEOUT:
            if DEBUG:
                print("_wait_for_output(): timeout after %s seconds" % remaining_timeout)
            break
        if DEBUG:
            print("_wait_for_output(): got %r" % (data,))
        # Keep the data in case we need to expect on it later.
        child._buffer.write(data)
        # We got some raw data.  Check if it's non-empty after ansi filtering.
        if data:
            got_data_already = True


def _wait_nonce(child):
    """
    Send a nonce to the child, then wait for the nonce, then backspace it.
    """
    # This function performs a clever trick.  When we use tab completion, we
    # need to handle a few variants of output.  Suppose the user enters
    # "foo.b\t".  We could see:
    #   1. No output.  There was nothing to complete, so there
    #      will be no output.
    #         In [1]: foo.b
    #   2. Regular completion
    #         In [1]: foo.bar
    #   3. Multiple possibilities (perhaps partial completion)
    #         In [1]: foo.b
    #         foo.bar1  foo.bar2
    #         In [1]: foo.bar
    #   4. Autoimport
    #         In [1]: foo.b
    #         [PYFLYBY] import foo
    #         In [1]: foo.bar
    #   5. Autoimport + multiple possibilities
    #         In [1]: foo.b
    #         [PYFLYBY] import foo
    #         In [1]: foo.b
    #         foo.bar1  foo.bar2
    #         In [1]: foo.bar
    # We need to handle all of these possibilities.
    # To do that, we send a nonce that IPython will echo back, *after* the
    # response to the tab.  This way we can wait for the nonce and
    # know exactly when IPython is done responding to the tab.
    # Some previous attempts:
    #   * Look for repeated "In [1]" to indicate that it's not a real prompt.
    #     That doesn't work well for continuation prompts ("...:").
    #   * Look for "\n" after tab and if so look for another repeated prompt.
    #     That doesn't work well for case 5 (difficult to detect triple
    #     prompts, especially if it's triple continuation prompts), and
    #     required an annoying timeout to handle the no-output case.
    logfile_read = child.logfile_read
    try:
        # Temporarily turn off logging of the output.  The caller doesn't need
        # to see the nonce or the backspaces.
        child.logfile_read = None
        # Send the nonce.
        nonce = "<SIG%s />" % (int(random.random()*1e9))
        child.send(nonce)
        # Wait for the nonce.
        child.expect_exact(nonce, timeout=DEFAULT_TIMEOUT)
        data_after_tab = child.before
        # Log what came before the nonce (but not the nonce itself).
        logfile_read.write(data_after_tab)
        # Delete the nonce we typed.
        child.send("\b" * len(nonce))
        child.expect(
            [r"\x1b\[%dD" % len(nonce), r"\x08\x1b\[K" * len(nonce), # IPython <  5
             r"\x08 \x08"*len(nonce) # GitHub CI seem to overwrite with spaces on top of moving cursor ?
            ],
            timeout=DEFAULT_TIMEOUT,
        )  # IPython >= 5 + rlipython

    finally:
        child.logfile_read = logfile_read


def _clean_backspace(arg):
    # Handle foo123\b\b\bbar => foobar
    left = b""
    right = arg
    while right:
        m = re.search(b"\x08+", right)
        if not m:
            break
        left = left + right[:m.start()]
        count = m.end() - m.start()
        left = left[:-count]
        right = right[m.end():]
    arg = left + right
    # Handle foo123\x1b[3Dbar => foobar
    left = b""
    right = arg
    while right:
        m = re.search(br"\x1b\[([0-9]+)D", right)
        if not m:
            break
        left = left + right[:m.start()]
        count = int(m.group(1))
        right = right[m.end():]
        if _IPYTHON_VERSION < (7,) and right.startswith(b"[PYFLYBY]"):
            # For purposes of comparing IPython output in prompt_toolkit mode,
            # include the pre-backspace stuff as a separate line.  TODO: do
            # this in a more less hacky way.
            left = left + b"\n"
        else:
            left = left[:-count]
    arg = left + right
    return arg



def _clean_ipython_output(result):
    """Clean up IPython output."""
    result0 = result
    # Canonicalize newlines.
    result = re.sub(b"\r+\n", b"\n", result)
    # Clean things like "    ESC[4D".
    result = _clean_backspace(result)
    # Make traceback output stable across IPython versions and runs.
    result = re.sub(re.compile(br"(^/.*?/)?<(ipython-input-[0-9]+-[0-9a-f]+|ipython console)>", re.M), b"<ipython-input>", result)
    result = re.sub(re.compile(br"^----> .*?\n", re.M), b"", result)
    # Remove trailing post-exit message.
    if _IPYTHON_VERSION >= (3,):
        result = re.sub(b"(?:Shutting down kernel|keeping kernel alive)\n?$", b"", result)
    # Work around
    # https://github.com/prompt-toolkit/python-prompt-toolkit/issues/886
    result = re.sub(br"Exception in default exception handler.*?During handling of the above exception, another exception occurred:.*?assert app\._is_running\nAssertionError\n", b"", result, flags=re.DOTALL)
    # CPR stuff from prompt-toolkit 2.0
    result = result.replace(b"WARNING: your terminal doesn't support cursor position requests (CPR).\n", b"")
    # Remove trailing "In [N]:", if any.
    result = re.sub(br"%s\n?$"%_IPYTHON_PROMPT1, b"", result)
    # Remove trailing "In [N]: exit()".
    result = re.sub(br"%sexit[(](?:keep_kernel=True)?[)]\n?$"%_IPYTHON_PROMPT1, b"", result)
    # Compress newlines.
    result = re.sub(br"\n\n+", b"\n", result)
    # Remove xterm title setting.
    result = re.sub(b"\x1b]0;[^\x1b\x07]*\x07", b"", result)
    # Remove BELs (done after the above codes, which use \x07 as a delimiter)
    result = result.replace(b"\x07", b"")
    # Remove code to clear to end of line. This is done here instead of in
    # decode() because _wait_nonce looks for this code.
    result = result.replace(b"\x1b[K", b"")
    result = result.lstrip()
    if _IPYTHON_VERSION >= (5,):  # and _IPYTHON_VERSION <= (8,):
        # In IPython 5 kernel/console/etc, it seems to be impossible to turn
        # off the banner.  For now just delete the output up to the first
        # prompt.
        result = re.sub(br".*?(In \[1\]:)", br"\1", result, flags=re.S)
    if DEBUG:
        print("_clean_ipython_output(): %r => %r" % (result0, result,))
    return result


@retry
def test_ipython_1(frontend):
    # Test that we can run ipython and get results back.
    ipython("""
        In [1]: print(6*7)
        42
        In [2]: 6*9
        Out[2]: 54
    """, frontend=frontend)


@retry
def test_ipython_assert_fail_1(frontend):
    with assert_fail():
        ipython("""
            In [1]: print(6*7)
            42
            In [2]: 6*9
            Out[2]: 53
        """, frontend=frontend)


@retry
def test_ipython_indented_block_4spaces_1(frontend):
    # Test that indented blocks work vs IPython's autoindent.
    # 4 spaces is the IPython default autoindent.
    ipython("""
        In [1]: if 1:
           ...:     print(6*7)
           ...:     print(6*9)
           ...:
        42
        54
        In [2]: 6*8
        Out[2]: 48
    """, frontend=frontend)



@retry
def test_ipython_indented_block_5spaces_1(frontend):
    # Test that indented blocks work vs IPython's autoindent.
    ipython("""
        In [1]: if 1:
           ...:         print(6*7)
           ...:         print(6*9)
           ...:
        42
        54
        In [2]: 6*8
        Out[2]: 48
        """, frontend=frontend)


@retry
def test_ipython_indented_block_6spaces_1(frontend):
    # Test that indented blocks work vs IPython's autoindent.
    ipython("""
        In [1]: if 1:
           ...:       print(6*7)
           ...:       print(6*9)
           ...:
        42
        54
        In [2]: 6*8
        Out[2]: 48
    """, frontend=frontend)


@retry
def test_ipython_indented_block_3spaces_1(frontend):
    # Test that indented blocks work vs IPython's autoindent.
    # Using ^U plus 3 spaces causes IPython to output "    \x08".
    ipython("""
        In [1]: if 1:
           ...:    print(6*7)
           ...:    print(6*9)
           ...:
        42
        54
        In [2]: 6*8
        Out[2]: 48
    """, frontend=frontend)


@retry
def test_ipython_indented_block_2spaces_1(frontend):
    # Test that indented blocks work vs IPython's autoindent.
    # Using ^U plus 2 spaces causes IPython 5 to output "    \x1b[2D  \x1b[2D".
    ipython("""
        In [1]: if 1:
           ...:   print(6*7)
           ...:   print(6*9)
           ...:
        42
        54
        In [2]: 6*8
        Out[2]: 48
    """, frontend=frontend)


@retry
def test_ipython_tab_1(frontend):
    # Test that our test harness works for tabs.
    ipython("""
        In [1]: import os
        In [2]: os.O_APP\tEND.__class__
        Out[2]: int
    """, frontend=frontend)

@retry
def test_ipython_tab_fail_1(frontend):
    # Test that our test harness works for tab when it should match nothing.
    ipython(
        """
        In [1]: import os
        In [2]: os.foo27817796\t()
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        ... in ...
        AttributeError: module 'os' has no attribute 'foo27817796'
    """,
        frontend=frontend,
    )


@pytest.mark.skipif(_IPYTHON_VERSION < (8, 27), reason='Multi-option tests are written for IPython 8.27+')
@retry
def test_ipython_tab_multi_1(frontend):
    # Test that our test harness works for tab when there are multiple matches
    # for tab completion. This test checks whether the common prefix gets added.
    ipython("""
        In [1]: def foo(): pass
        In [2]: foo.xyz1 = 111
        In [3]: foo.xyz2 = 222
        In [4]: foo.xy\t
        In [4]: foo.xyz\x06
        ...
        ...
        ...
        AttributeError: 'function' object has no attribute 'xyz'
    """, frontend=frontend, args=['--IPCompleter.use_jedi=False'])


@pytest.mark.skipif(_IPYTHON_VERSION < (8, 27), reason='Multi-option tests are written for IPython 8.27+')
@retry
def test_ipython_tab_multi_2(frontend):
    # Test that our test harness works for tab when there are multiple matches
    # for tab completion. This test checks if multiple suggestions are shown.
    ipython("""
        In [1]: def foo(): pass
        In [2]: foo.xyz1 = 111
        In [3]: foo.xyz2 = 222
        In [4]: foo.xyz\t
        In [4]: foo.xyz
        .xyz1 .xyz2
        ...
        ...
        ...
        ...
        AttributeError: 'function' object has no attribute 'xyz'
    """, frontend=frontend, args=['--IPCompleter.use_jedi=False'])


@retry
def test_pyflyby_file_1():
    # Verify that our test setup is getting the right pyflyby.
    f = os.path.realpath(pyflyby.__file__.replace(".pyc", ".py"))
    ipython("""
        In [1]: import os, pyflyby
        In [2]: print(os.path.realpath(pyflyby.__file__.replace(".pyc", ".py")))
        {f}
    """.format(f=f))


@retry
def test_pyflyby_version_1():
    # Verify that our test setup is getting the right pyflyby.
    ipython("""
        In [1]: import pyflyby
        In [2]: print(pyflyby.__version__)
        {pyflyby.__version__}
    """.format(pyflyby=pyflyby))


@retry
def test_ipython_file_1():
    # Verify that our test setup is getting the right IPython.
    f = os.path.realpath(IPython.__file__)
    ipython("""
        In [1]: import IPython, os
        In [2]: print(os.path.realpath(IPython.__file__))
        {f}
    """.format(f=f))


@retry
def test_ipython_version_1():
    # Verify that our test setup is getting the right IPython.
    ipython("""
        In [1]: import IPython
        In [2]: print(IPython.__version__)
        {IPython.__version__}
    """.format(IPython=IPython))


@retry
def test_autoimport_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b'@'+b64decode('SGVsbG8=')+b'@'
        [PYFLYBY] from base64 import b64decode
        Out[2]: b'@Hello@'
    """)


@retry
def test_no_autoimport_1():
    # Test that without pyflyby installed, we do get NameError.  This is
    # really a test that our testing infrastructure is OK and not accidentally
    # picking up pyflyby configuration installed in a system or user config.
    ipython(
        """
        In [1]: b'@'+b64decode('SGVsbG8=')+b'@'
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64decode' is not defined
    """
    )


def test_load_ext_1():
    # Test that %load_ext works.
    ipython("""
        In [1]: Decimal(55479415)
        ....
        NameError: name 'Decimal' is not defined
        In [2]: %load_ext pyflyby
        In [3]: Decimal(43660783)
        [PYFLYBY] from decimal import Decimal
        Out[3]: Decimal('43660783')
    """)


@retry
def test_unload_ext_1():
    # Test that %unload_ext works.
    # Autoimporting should stop working, but previously imported thi
    ipython("""
        In [1]: b64encode(b'tortoise')
        ....
        NameError: name 'b64encode' is not defined
        In [2]: %load_ext pyflyby
        In [3]: b64encode(b'tortoise')
        [PYFLYBY] from base64 import b64encode
        Out[3]: b'dG9ydG9pc2U='
        In [4]: %unload_ext pyflyby
        In [5]: b64decode(b'aGFyZQ==')
        ....
        NameError: name 'b64decode' is not defined
        In [6]: b64encode(b'turtle')
        Out[6]: b'dHVydGxl'
    """)



@retry
def test_reload_ext_1():
    # Test that autoimporting still works after %reload_ext.
    ipython("""
        In [1]: b64encode(b'east')
        ....
        NameError: name 'b64encode' is not defined
        In [2]: %load_ext pyflyby
        In [3]: b64encode(b'east')
        [PYFLYBY] from base64 import b64encode
        Out[3]: b'ZWFzdA=='
        In [4]: %reload_ext pyflyby
        In [5]: b64decode(b'd2VzdA==')
        [PYFLYBY] from base64 import b64decode
        Out[5]: b'west'
    """)


@retry
def test_reload_ext_reload_importdb_1(tmp):
    # Test that %reload_ext causes the importdb to be refreshed.
    writetext(tmp.file, "from itertools import repeat\n")
    ipython(
        """
        In [1]: %load_ext pyflyby
        In [2]: list(repeat(3,4))
        [PYFLYBY] from itertools import repeat
        Out[2]: [3, 3, 3, 3]
        In [3]: list(combinations('abc',2))
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'combinations' is not defined
        In [4]: with open('{tmp.file}', 'a') as f:
           ...:   f.write('from itertools import combinations\\n')
           ...:
        In [5]: list(combinations('abc',2))
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'combinations' is not defined
        In [6]: %reload_ext pyflyby
        In [7]: list(combinations('abc',2))
        [PYFLYBY] from itertools import combinations
        Out[7]: [('a', 'b'), ('a', 'c'), ('b', 'c')]
    """.format(
            tmp=tmp
        ),
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_reload_ext_retry_failed_imports_1(tmp):
    # Verify that %xreload_ext causes us to retry imports that we previously
    # decided not to retry.
    writetext(
        tmp.dir / "hippo84402009.py",
        """
        import sys
        data = sys.__dict__.setdefault('hippo84402009_attempts', 0)
        sys.hippo84402009_attempts += 1
        print('hello from hippo84402009: attempt %d'
              % sys.hippo84402009_attempts)
        1/0
    """,
    )
    writetext(tmp.file, "from hippo84402009 import rhino13609135")
    ipython(
        """
        In [1]: %load_ext pyflyby
        In [2]: rhino13609135
        [PYFLYBY] from hippo84402009 import rhino13609135
        hello from hippo84402009: attempt 1
        [PYFLYBY] Error attempting to 'from hippo84402009 import rhino13609135': ZeroDivisionError: division by zero
        ....
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'rhino13609135' is not defined
        In [3]: rhino13609135
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'rhino13609135' is not defined
        In [4]: %reload_ext pyflyby
        In [5]: rhino13609135
        [PYFLYBY] from hippo84402009 import rhino13609135
        hello from hippo84402009: attempt 2
        [PYFLYBY] Error attempting to 'from hippo84402009 import rhino13609135': ZeroDivisionError: division by zero
        ....
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'rhino13609135' is not defined
    """,
        PYTHONPATH=tmp.dir,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_symbol_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode
        [PYFLYBY] from base64 import b64decode
        Out[2]: <function ...b64decode...>
    """)


@retry
def test_autoimport_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1: print(b64decode(b'SGVsbG8=').decode('utf-8'))
        [PYFLYBY] from base64 import b64decode
        Hello
    """)


@retry
def test_autoimport_multiple_imports_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print((b64encode(b"koala"), b64decode(b"a2FuZ2Fyb28=")))
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] from base64 import b64encode
        (b'a29hbGE=', b'kangaroo')
    """)


@retry
def test_autoimport_multiline_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print(b64decode(b'dHVydGxl').decode('utf-8'))
           ...:
        [PYFLYBY] from base64 import b64decode
        turtle
        In [3]: if 1: print(b64decode(b'bGFtYQ==').decode('utf-8'))
        lama
    """)


@retry
def test_autoimport_multiline_continued_statement_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     (sys.
           ...:         stdout
           ...:             .buffer
           ...:                 .write(
           ...:                     b64decode(
           ...:                         'bWljcm9waG9uZQ==')))
           ...:
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] import sys
        microphone
        In [3]: if 1: sys.stdout.buffer.write(b64decode('bG91ZHNwZWFrZXI='))
        loudspeaker
    """, frontend=frontend)


@retry
def test_autoimport_multiline_continued_statement_fake_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print(unknown_symbol_37320899.
           ...:         b64encode
           ...:         )
           ...:
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ....
        NameError: name 'unknown_symbol_37320899' is not defined
        In [3]: if 1:
           ...:     print(b64encode(b'y').decode('utf-8'))
           ...:
        [PYFLYBY] from base64 import b64encode
        eQ==
        In [4]: if 1: print(b64decode('YmFzZWJhbGw=').decode('utf-8'))
        [PYFLYBY] from base64 import b64decode
        baseball
    """, frontend=frontend)


@retry
def test_autoimport_pyflyby_path_1(tmp):
    writetext(tmp.file, "from itertools import product\n")
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: list(product('ab','cd'))
        [PYFLYBY] from itertools import product
        Out[2]: [('a', 'c'), ('a', 'd'), ('b', 'c'), ('b', 'd')]
        In [3]: groupby
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'groupby' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_autocall_arg_1():
    # Verify that we can autoimport the argument of an autocall.
    if IPython.version_info < (7, 17):
        # The autocall arrows are printed twice in newer versions of IPython
        # (https://github.com/ipython/ipython/issues/11714).
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: bytes.upper b64decode('a2V5Ym9hcmQ=')
            ------> bytes.upper(b64decode('a2V5Ym9hcmQ='))
            ------> bytes.upper(b64decode('a2V5Ym9hcmQ='))
            [PYFLYBY] from base64 import b64decode
            Out[2]: b'KEYBOARD'
        """, autocall=True)
    else:
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: bytes.upper b64decode('a2V5Ym9hcmQ=')
            ------> bytes.upper(b64decode('a2V5Ym9hcmQ='))
            [PYFLYBY] from base64 import b64decode
            Out[2]: b'KEYBOARD'
        """, autocall=True)

@retry
def test_autoimport_autocall_function_1():
    # Verify that we can autoimport the function to autocall.
    if IPython.version_info < (7, 17):
        # The autocall arrows are printed twice in newer versions of IPython
        # (https://github.com/ipython/ipython/issues/11714).
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: b64decode 'bW91c2U='
            [PYFLYBY] from base64 import b64decode
            ------> b64decode('bW91c2U=')
            ------> b64decode('bW91c2U=')
            Out[2]: b'mouse'
        """, autocall=True)
    else:
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: b64decode 'bW91c2U='
            [PYFLYBY] from base64 import b64decode
            ------> b64decode('bW91c2U=')
            Out[2]: b'mouse'
        """, autocall=True)

@retry
def test_autoimport_multiple_candidates_ast_transformer_1(tmp):
    # Verify that we print out all candidate autoimports, when there are
    # multiple.
    writetext(
        tmp.file,
        """
        import foo23596267 as bar
        import foo50853429 as bar
        import foo47979882 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo23596267 as bar
        [PYFLYBY]   import foo47979882 as bar
        [PYFLYBY]   import foo50853429 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_multiple_candidates_repeated_1(tmp):
    # Verify that we print out the candidate list for another cell.
    writetext(
        tmp.file,
        """
        import foo70603247 as bar
        import foo31703722 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo31703722 as bar
        [PYFLYBY]   import foo70603247 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
        In [3]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo31703722 as bar
        [PYFLYBY]   import foo70603247 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_multiple_candidates_multiple_in_expression_1(tmp):
    # Verify that if an expression contains multiple ambiguous imports, we
    # report each one.
    writetext(
        tmp.file,
        """
        import foo85957810 as foo
        import foo35483918 as foo
        import bar25290002 as bar
        import bar36166308 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: foo+bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import bar25290002 as bar
        [PYFLYBY]   import bar36166308 as bar
        [PYFLYBY] Multiple candidate imports for foo.  Please pick one:
        [PYFLYBY]   import foo35483918 as foo
        [PYFLYBY]   import foo85957810 as foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'foo' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_multiple_candidates_repeated_in_expression_1(tmp):
    # Verify that if an expression contains an ambiguous import twice, we only
    # report it once.
    writetext(
        tmp.file,
        """
        import foo83958492 as bar
        import foo29432668 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar+bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo29432668 as bar
        [PYFLYBY]   import foo83958492 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_autoimport_multiple_candidates_ofind_1(tmp):
    # Verify that the multi-candidate menu works even with ofind.
    writetext(tmp.file, """
        import foo45415553 as bar
        import foo37472809 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar?
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo37472809 as bar
        [PYFLYBY]   import foo45415553 as bar
        Object `bar` not found.
    """, PYFLYBY_PATH=tmp.file)


@retry
def test_autoimport_multiple_candidates_multi_joinpoint_1(tmp):
    # Verify that the autoimport menu is only printed once, even when multiple
    # joinpoints apply (autocall=>ofind and ast_importer).
    writetext(
        tmp.file,
        """
        import foo85223658 as bar
        import foo10735265 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
        autocall=True,
    )


@retry
def test_autoimport_multiple_candidates_multi_joinpoint_repeated_1(tmp):
    # We should report the multiple candidate issue again if asked again.
    writetext(
        tmp.file,
        """
        import foo85223658 as bar
        import foo10735265 as bar
    """,
    )
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
        In [3]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
        autocall=True,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_basic_1():
    # Verify that tab completion works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64deco\tde('eHl6enk=')
        [PYFLYBY] from base64 import b64decode
        Out[2]: b'xyzzy'
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_multiple_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print(b64\t
        In [2]: print(b64
        b64decode b64encode
        In [2]: print(b64\x06decode)
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_partial_multiple_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print(b6\t
        In [2]: print(b64\x06decode)
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_import_check_1():
    # Check importing into the namespace.  If we use b64decode from base64,
    # then b64decode should be imported into the namespace, but base64 should
    # not.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 'base64' in globals()
        Out[2]: False
        In [3]: 'b64decode' in globals()
        Out[3]: False
        In [4]: b64deco\tde('UnViaWNvbg==')
        [PYFLYBY] from base64 import b64decode
        Out[4]: b'Rubicon'
        In [5]: 'base64' in globals()
        Out[5]: False
        In [6]: 'b64decode' in globals()
        Out[6]: True
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_instance_identity_1():
    # Verify that automatic symbols give the same instance (i.e., no proxy
    # objects involved).
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: f = b64deco\tde
        [PYFLYBY] from base64 import b64decode
        In [3]: f is __import__('base64').b64decode
        Out[3]: True
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_member_1(frontend):
    # Verify that tab completion in members works.
    # We expect "base64.b64d" to be reprinted again after the [PYFLYBY] log
    # line.  (This differs from the "b64deco\t" case: in that case, nothing
    # needs to be imported to satisfy the tab completion, and therefore no log
    # line was printed.  OTOH, for an input of "base64.b64deco\t", we need to
    # first do an automatic "import base64", which causes log output during
    # the prompt, which means reprinting the input so far.)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: base64.b64d\t
        [PYFLYBY] import base64
        In [2]: base64.b64decode('bW9udHk=')
        Out[2]: b'monty'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_member_multiple_1(frontend):
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print(base64.b64\t
        In [2]: print(base64.b64
        .b64decode .b64encode
        [PYFLYBY] import base64
        In [2]: print(base64.b64)
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        ... in ...
        AttributeError: module 'base64' has no attribute 'b64'
    """,
        frontend=frontend,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_member_partial_multiple_1(frontend):
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print(base64.b6\t
        [PYFLYBY] import base64
        In [2]: print(base64.b64)
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        ... in ...
        AttributeError: module 'base64' has no attribute 'b64'
    """,
        frontend=frontend,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_import_module_as_1(frontend, tmp):
    writetext(tmp.file, "import base64 as b64\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64.b64d\t
        [PYFLYBY] import base64 as b64
        In [2]: b64.b64decode('cm9zZWJ1ZA==')
        Out[2]: b'rosebud'
    """, PYFLYBY_PATH=tmp.file, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_statement_1():
    # Verify that tab completion in statements works.  This requires a more
    # sophisticated code path than test_complete_symbol_basic_1.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: x = b64deco\tde('SHVudGVy')
        [PYFLYBY] from base64 import b64decode
        In [3]: x
        Out[3]: b'Hunter'
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_multiline_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print(b64deco\tde('emVicmE=').decode('utf-8'))
           ...:     print(42)
           ...:
        [PYFLYBY] from base64 import b64decode
        zebra
        42
        In [3]: if 1: print(b64decode('dGlnZXI=').decode('utf-8'))
        tiger
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_multiline_statement_member_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print(base64.b64d\t
        [PYFLYBY] import base64
        In [2]: if 1:
           ...:     print(base64.b64decode('Z2lyYWZmZQ=='))
           ...:     print(42)
           ...:
        b'giraffe'
        42
        In [3]: print(b64d\tecode('bGlvbg=='))
        [PYFLYBY] from base64 import b64decode
        b'lion'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_autocall_arg_1():
    # Verify that tab completion works with autocall.
    if IPython.version_info < (7,17):
        # The autocall arrows are printed twice in newer versions of IPython
        # (https://github.com/ipython/ipython/issues/11714).
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: bytes.upper b64deco\tde('Q2hld2JhY2Nh')
            ------> bytes.upper(b64decode('Q2hld2JhY2Nh'))
            ------> bytes.upper(b64decode('Q2hld2JhY2Nh'))
            [PYFLYBY] from base64 import b64decode
            Out[2]: b'CHEWBACCA'
        """, autocall=True)
    else:
        # IPython 7.17+ should have fixed double autocall
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: bytes.upper b64deco\tde('Q2hld2JhY2Nh')
            ------> bytes.upper(b64decode('Q2hld2JhY2Nh'))
            [PYFLYBY] from base64 import b64decode
            Out[2]: b'CHEWBACCA'
        """, autocall=True)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_any_module_1(frontend, tmp):
    # Verify that completion and autoimport works for an arbitrary module in
    # $PYTHONPATH.
    writetext(tmp.dir/"m18908697_foo.py", """
       def f_68421204(): return 'good'
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: m18908697_\tfoo.f_68421204()
        [PYFLYBY] import m18908697_foo
        Out[2]: 'good'
    """, PYTHONPATH=tmp.dir, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_any_module_member_1(frontend, tmp):
    # Verify that completion on members works for an arbitrary module in
    # $PYTHONPATH.
    writetext(tmp.dir/"m51145108_foo.py", """
        def f_76313558_59577191(): return 'ok'
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        [PYFLYBY] import m51145108_foo
        In [2]: m51145108_\tfoo.f_76313558_\t
        In [2]: m51145108_foo.f_76313558_59577191()
        Out[2]: 'ok'
    """, PYTHONPATH=tmp.dir, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_bad_1(frontend, tmp):
    # Verify that if we have a bad item in known imports, we complete it still.
    writetext(tmp.file, "import foo_31221052_bar\n")
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: foo_31221052_\tbar
        [PYFLYBY] import foo_31221052_bar
        [PYFLYBY] Error attempting to 'import foo_31221052_bar': ModuleNotFoundError: No module named 'foo_31221052_bar'
        ....
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'foo_31221052_bar' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
        frontend=frontend,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_bad_as_1(frontend, tmp):
    writetext(tmp.file, "import foo_86487172 as bar_98073069_quux\n")
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar_98073069_\tquux.asdf
        [PYFLYBY] import foo_86487172 as bar_98073069_quux
        [PYFLYBY] Error attempting to 'import foo_86487172 as bar_98073069_quux': ModuleNotFoundError: No module named 'foo_86487172'
        ....
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'bar_98073069_quux' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
        frontend=frontend,
    )


@retry
def test_complete_symbol_getitem_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: apples = ['McIntosh', 'PinkLady']
        In [3]: apples[1].l\t
        In [3]: apples[1].l
        ljust()  lower()  lstrip()
        In [3]: apples[1].l\x06ow\ter()
        Out[3]: 'pinklady'
    """,
            frontend=frontend)


def test_complete_symbol_getitem_no_jedi_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: apples = ['McIntosh', 'PinkLady']
        In [3]: apples[1].l\t
        In [3]: apples[1].l
        .ljust  .lower  .lstrip
        In [3]: apples[1].l\x06ow\ter()
        Out[3]: 'pinklady'
    """,
            args=['--IPCompleter.use_jedi=False'],
            frontend=frontend)


@pytest.mark.parametrize('evaluation', _TESTED_EVALUATION_SETTINGS)
def test_complete_symbol_eval_1(evaluation):
    ipython(f"""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %config IPCompleter.{evaluation}
        In [3]: apple = 'Fuji'
        In [4]: apple.lower()[0].stri\tp()
        Out[4]: 'f'
    """)



@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@pytest.mark.parametrize('evaluation', _TESTED_EVALUATION_SETTINGS)
def test_complete_symbol_eval_autoimport_1(frontend, evaluation):
    template = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %config IPCompleter.{0}
        In [3]: os.sep.strip().lst\t{1}
        Out[3]: <function str.lstrip(chars=None, /)>
    """

    scenario_a = """
        [PYFLYBY] import os
        In [3]: os.sep.strip().lst\trip"""
    scenario_b = """
        [PYFLYBY] import os
        In [3]: os.sep.strip().lstrip"""

    try:
        ipython(template.format(evaluation, scenario_a), frontend=frontend)
    except pytest.fail.Exception:
        ipython(template.format(evaluation, scenario_b), frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_complete_symbol_error_in_getattr_1(frontend):
    # Verify that if there's an exception inside some custom object's getattr,
    # we don't get confused.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: class Naughty:
           ...:     def __getattr__(self, k):
           ...:         1/0
           ...:
        In [3]: n = Naughty()
        In [4]: n.foo.b\t\x06
        ---------------------------------------------------------------------------
        ZeroDivisionError                         Traceback (most recent call last)
        ....
        ZeroDivisionError: division by zero
        In [5]: sys.settra\t
        [PYFLYBY] import sys
        In [5]: sys.settrace
        Out[5]: <...settrace...>
    """, frontend=frontend)


def test_property_no_superfluous_access_1(tmp):
    # Verify that we don't trigger properties more than once.
    writetext(tmp.dir/"rathbun38356202.py", """
        class A(object):
            @property
            def ellsworth(self):
                print("edgegrove")
                return "darlington"
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: a = rathbun38356202.A()
        [PYFLYBY] import rathbun38356202
        In [3]: a.ellsworth
        edgegrove
        Out[3]: 'darlington'
    """, PYTHONPATH=tmp.dir)


@retry
def test_disable_reenable_autoimport_1():
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: b64encode(b'blue')
        [PYFLYBY] from base64 import b64encode
        Out[3]: b'Ymx1ZQ=='
        In [4]: pyflyby.disable_auto_importer()
        In [5]: b64decode('cmVk')        # expect NameError since no auto importer
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64decode' is not defined
        In [6]: b64encode(b'green')       # should still work because already imported
        Out[6]: b'Z3JlZW4='
        In [7]: pyflyby.enable_auto_importer()
        In [8]: b64decode('eWVsbG93')    # should work now
        [PYFLYBY] from base64 import b64decode
        Out[8]: b'yellow'
    """
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_disable_reenable_completion_1():
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: b64enco\tde(b'flower')
        [PYFLYBY] from base64 import b64encode
        Out[3]: b'Zmxvd2Vy'
        In [4]: pyflyby.disable_auto_importer()
        In [5]: b64deco\t('Y2xvdWQ=') # expect NameError since no auto importer
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64deco' is not defined
        In [6]: b64enco\tde(b'tree') # should still work because already imported
        Out[6]: b'dHJlZQ=='
        In [7]: pyflyby.enable_auto_importer()
        In [8]: b64deco\tde('Y2xvdWQ=') # should work now
        [PYFLYBY] from base64 import b64decode
        Out[8]: b'cloud'
    """
    )


@retry
def test_pinfo_1(tmp):
    # Test that pinfo (ofind hook) works.
    writetext(tmp.dir/"m17426814.py", """
        def f34229186():
            'hello from '  '3422'  '9186'
    """)
    writetext(tmp.file, "from m17426814 import f34229186\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: f34229186?
        [PYFLYBY] from m17426814 import f34229186
        ....
        Docstring:....hello from 34229186....
    """, PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.file)


@retry
def test_error_during_auto_import_symbol_1(tmp):
    writetext(tmp.file, "3+")
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: 6*7
        Out[3]: 42
        In [4]: unknown_symbol_68470042
        [PYFLYBY] SyntaxError: While parsing ...: invalid syntax (..., line 1)
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_68470042' is not defined
        In [5]: unknown_symbol_76663387
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_76663387' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_error_during_auto_import_expression_1(tmp):
    writetext(tmp.file, "3+")
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: 6*7
        Out[3]: 42
        In [4]: 42+unknown_symbol_72161870
        [PYFLYBY] SyntaxError: While parsing ...: invalid syntax (..., line 1)
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_72161870' is not defined
        In [5]: 42+unknown_symbol_48517397
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_48517397' is not defined
    """,
        PYFLYBY_PATH=tmp.file,
    )


@retry
def test_error_during_completion_1(frontend, tmp):
    writetext(tmp.file, "3+")
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: 100
        Out[3]: 100
        In [4]: unknown_symbol_14954304_\t
        [PYFLYBY] SyntaxError: While parsing ...: invalid syntax (..., line 1)
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        In [4]: unknown_symbol_14954304_\x06foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_14954304_foo' is not defined
        In [5]: 200
        Out[5]: 200
        In [6]: unknown_symbol_69697066_\t\x06foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'unknown_symbol_69697066_foo' is not defined
        In [7]: 300
        Out[7]: 300
    """,
        PYFLYBY_PATH=tmp.file,
        frontend=frontend,
    )


@retry
def test_syntax_error_in_user_code_1():
    # Verify that we don't inadvertently disable the autoimporter due to
    # a syntax error in the interactive command.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 1/
        ....
        SyntaxError: invalid syntax
        In [3]: b64decode("bWlkbmlnaHQ=")
        [PYFLYBY] from base64 import b64decode
        Out[3]: b'midnight'
    """)


@retry
def test_run_1(tmp):
    # Test that %run works and autoimports.
    writetext(tmp.file, """
        print('hello')
        print(b64decode('RXVjbGlk').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        hello
        Euclid
    """.format(tmp=tmp))


@retry
def test_run_repeat_1(tmp):
    # Test that repeated %run works, and continues autoimporting, since we
    # start from a fresh namespace each time (since no "-i" option to %run).
    writetext(tmp.file, """
        print(b64decode('Q2FudG9y').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Cantor
        In [3]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Cantor
    """.format(tmp=tmp))


@retry
def test_run_separate_script_namespace_1(tmp):
    # Another explicit test that we start %run from a fresh namespace
    writetext(tmp.file, """
        print(b64decode('UmllbWFubg==').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode('Rmlib25hY2Np')
        [PYFLYBY] from base64 import b64decode
        Out[2]: b'Fibonacci'
        In [3]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Riemann
    """.format(tmp=tmp))


@retry
def test_run_separate_script_namespace_2(tmp):
    # Another explicit test that we start %run from a fresh namespace, not
    # inheriting even explicitly defined functions.
    writetext(tmp.file, """
        print(b64decode('SGlsYmVydA==').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def b64decode(x):
           ...:     return "booger"
           ...:
        In [3]: b64decode('x')
        Out[3]: 'booger'
        In [4]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Hilbert
    """.format(tmp=tmp))


@retry
def test_run_modify_interactive_namespace_1(tmp):
    # Verify that %run does affect the interactive namespace.
    writetext(tmp.file, """
        x = b64decode('RmVybWF0')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        In [3]: x
        Out[3]: b'Fermat'
        In [4]: b64decode('TGFwbGFjZQ==')
        Out[4]: b'Laplace'
    """.format(tmp=tmp))


@retry
def test_run_i_auto_import_1(tmp):
    # Verify that '%run -i' works and autoimports.
    writetext(tmp.file, """
        print(b64decode('RGVzY2FydGVz').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -i {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Descartes
        In [3]: b64decode('R2F1c3M=')
        Out[3]: b'Gauss'
    """.format(tmp=tmp))

@pytest.mark.skip(reason="This is one of the slowest test and it's xfail")
@pytest.mark.xfail(strict=True)
def test_run_d_donterase(tmp):
    """
    accessing f_locals may reset namespace,
    here we check that myvar changes after assignment in the debugger.
    """
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def simple_f():
           ...:     myvar = 1
           ...:     print(myvar)
           ...:     1/0
           ...:     print(myvar)
           ...: simple_f()
           ...:
        1
        ---------------------------------------------------------------------------
        ZeroDivisionError                         Traceback (most recent call last)
        ... in ...
              4     1/0
              5     print(myvar)
        ... in simple_f()
              2 myvar = 1
              3 print(myvar)
              5 print(myvar)
        ZeroDivisionError: division by zero
        In [3]: %debug
        > <ipython-input>(4)simple_f()
              2     myvar = 1
              3     print(myvar)
              5     print(myvar)
              6 simple_f()
        ipdb> myvar
        1
        ipdb> myvar = 2
        ipdb> myvar
        2
        ipdb> c
"""
    )


@retry
def test_run_i_already_imported_1(tmp):
    # Verify that '%run -i' inherits the interactive namespace.
    writetext(tmp.file, """
        print(b64decode(k).decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode('R3JvdGhlbmRpZWNr')
        [PYFLYBY] from base64 import b64decode
        Out[2]: b'Grothendieck'
        In [3]: k = 'QXJjaGltZWRlcw=='
        In [4]: run -i {tmp.file}
        Archimedes
    """.format(tmp=tmp))


@retry
def test_run_i_repeated_1(tmp):
    # Verify that '%run -i' affects the next namespace of the next '%run -i'.
    writetext(tmp.file, """
        print(b64decode('S29sbW9nb3Jvdg==').decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -i {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Kolmogorov
        In [3]: run -i {tmp.file}
        Kolmogorov
    """.format(tmp=tmp))


@retry
def test_run_i_locally_defined_1(tmp):
    # Verify that '%run -i' can inherit interactively defined symbols.
    writetext(tmp.file, """
        print(b64decode('zzz'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def b64decode(x):
           ...:     return "Bernoulli"
           ...:
        In [3]: run -i {tmp.file}
        Bernoulli
    """.format(tmp=tmp))


@retry
def test_run_syntax_error_1(tmp):
    # Verify that a syntax error in a user-run script doesn't affect
    # autoimporter functionality.
    writetext(tmp.file, """
        print('hello')
        print(b64decode('UHl0aGFnb3Jhcw==').decode('utf-8'))
        1 /
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        ....
        SyntaxError: invalid syntax....
        In [3]: b64decode('Q29ud2F5')
        [PYFLYBY] from base64 import b64decode
        Out[3]: b'Conway'
    """.format(tmp=tmp))


@retry
def test_run_name_main_1(tmp):
    # Verify that __name__ == "__main__" in a %run script.
    writetext(tmp.file, """
        print(b64encode(__name__.encode('utf-8')).decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64encode
        X19tYWluX18=
    """.format(tmp=tmp))


@retry
def test_run_name_not_main_1(tmp):
    # Verify that __name__ == basename(filename) using '%run -n'.
    f = writetext(tmp.dir/"f81564382.py", """
        print(b64encode(__name__.encode('utf-8')).decode('utf-8'))
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -n {f}
        [PYFLYBY] from base64 import b64encode
        ZjgxNTY0Mzgy
    """.format(f=f))


@retry
def test_timeit_1():
    # Verify that %timeit works.
    ipython(u"""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %timeit -n 2 -r 1 b64decode('TWljaGVsYW5nZWxv')
        [PYFLYBY] from base64 import b64decode
        ... per loop (mean ± std. dev. of 1 run, 2 loops each)
        In [3]: %timeit -n 2 -r 1 b64decode('RGF2aWQ=')
        ... per loop (mean ± std. dev. of 1 run, 2 loops each)
    """)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_timeit_complete_1(frontend):
    # Verify that tab completion works with %timeit.
    ipython(u"""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %timeit -n 2 -r 1 b64de\tcode('cGlsbG93')
        [PYFLYBY] from base64 import b64decode
        ... per loop (mean ± std. dev. of 1 run, 2 loops each)
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_timeit_complete_menu_1(frontend):
    # Verify that menu tab completion works with %timeit.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: timeit -n 2 -r 1 b64\t
        In [2]: timeit -n 2 -r 1 b64
        b64decode b64encode
        In [2]: timeit -n 2 -r 1 b64\x06de\tcode('YmxhbmtldA==')
        [PYFLYBY] from base64 import b64decode
        ... per loop (mean ± std. dev. of 1 run, 2 loops each)
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@pytest.mark.skipif(_IPYTHON_VERSION < (8, 27), reason='Multi-option tests are written for IPython 8.27+')
@retry
def test_timeit_complete_autoimport_member_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: timeit -n 2 -r 1 base64.b64\t
        In [2]: timeit -n 2 -r 1 base64.b64
        .b64decode .b64encode
        [PYFLYBY] import base64
        In [2]: timeit -n 2 -r 1 base64.b64\x06dec\tode('bWF0dHJlc3M=')
        ... per loop (mean ± std. dev. of 1 run, 2 loops each)
    """, frontend=frontend)


@retry
def test_noninteractive_timeit_unaffected_1():
    # Verify that the regular timeit module is unaffected, i.e. that we only
    # hooked the IPython wrapper.
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: timeit.timeit("base64.b64decode", number=1)
        [PYFLYBY] import timeit
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        ....
        NameError: name 'base64' is not defined
    """
    )


@retry
def test_time_1(frontend):
    # Verify that %time autoimport works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64decode("dGVsZXBob25l")
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: b'telephone'
    """, frontend=frontend)


@retry
def test_time_repeat_1(frontend):
    # Verify that %time autoimport works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64decode("dGVsZWdyYXBo")
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: b'telegraph'
        In [3]: %time b64decode("ZW1haWw=")
        CPU times: ...
        Wall time: ...
        Out[3]: b'email'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_time_complete_1(frontend):
    # Verify that tab completion works with %time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64de\tcode('c2hpcnQ=')
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: b'shirt'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_time_complete_menu_1(frontend):
    # Verify that menu tab completion works with %time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: time b64\t
        In [2]: time b64
        b64decode b64encode
        In [2]: time b64\x06d\tecode('cGFudHM=')
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: b'pants'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@pytest.mark.skipif(_IPYTHON_VERSION < (8, 27), reason='Multi-option tests are written for IPython 8.27+')
@retry
def test_time_complete_autoimport_member_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: time base64.b64\t
        In [2]: time base64.b64
        .b64decode .b64encode
        [PYFLYBY] import base64
        In [2]: time base64.b64\x06dec\tode('amFja2V0')
        CPU times: ...
        Wall time: ...
        Out[2]: b'jacket'
    """, frontend=frontend)


@retry
def test_prun_1():
    # Verify that %prun works, autoimports the first time, but not the second
    # time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %prun b64decode("RWluc3RlaW4=")
        [PYFLYBY] from base64 import b64decode
        .... function calls in ... seconds
        ....
        In [3]: b64decode("SGF3a2luZw==")
        Out[3]: b'Hawking'
        In [4]: %prun b64decode("TG9yZW50eg==")
        .... function calls in ... seconds
        ....
    """)


@retry
def test_noninteractive_profile_unaffected_1():
    # Verify that the profile module itself is not affected (i.e. verify that
    # we only hook the IPython usage of it).
    ipython(
        """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: profile.Profile().run("base64.b64decode")
        [PYFLYBY] import profile
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        ....
        NameError: name 'base64' is not defined
    """
    )


@retry
def test_error_during_enable_1():
    # Verify that if an error occurs during enabling, that we disable the
    # autoimporter.  Verify that we don't attempt to re-enable again.
    ipython(
        """
        In [1]: import pyflyby
        In [2]: pyflyby._interactive.AutoImporter._enable_internal = None
        In [3]: pyflyby.enable_auto_importer()
        [PYFLYBY] TypeError: 'NoneType' object is not callable
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        In [4]: print('hello')
        hello
        In [5]: sys
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'sys' is not defined
        In [6]: pyflyby.enable_auto_importer()
        [PYFLYBY] Not reattempting to enable auto importer after earlier error
    """
    )


# We could write to jupyter_console_config.py and set JUPYTER_CONFIG_DIR, but
# it only supports highlight_matching_brackets, not
# display_completions='readlinelike', so any test that uses tab completion
# won't work.


@pytest.mark.skip(
    reason="jupyter client is now completely async but JupyterConsole is not"
)
@pytest.mark.parametrize("sendeof", [False, True])
def test_ipython_console_1(sendeof):
    # Verify that autoimort land tab completion work in IPython console.
    # We retry a few times until success (via the @retry decorator) because
    # for some versions of ipython, in some configurations, 'ipython console'
    # occasionally hangs on startup; not sure why, but it seems unrelated to
    # pyflyby, since it happens before any pyflyby commands.
    # The reason for the 'In [1]: x = 91976012' is to make this test more
    # robust in older versions of IPython.  In some versions (0.x), IPython
    # console occasionally doesn't print the first output (i.e. Out[1]).  We
    # work around this by first running something where we don't expect an
    # Out[1].
    if sendeof and _IPYTHON_VERSION >= (5,): pytest.skip()
    ipython("""
        In [1]: x = 91976012
        In [2]: 'acorn'
        Out[2]: 'acorn'
        In [3]: import pyflyby; pyflyby.enable_auto_importer()
        In [4]: b64deco\tde('cGVhbnV0')
        [PYFLYBY] from base64 import b64decode
        Out[4]: b'peanut'
    """, args='console', sendeof=sendeof)


@pytest.mark.skip(
    reason="jupyter client is now completely async but JupyterConsole is not"
)
def test_ipython_kernel_console_existing_1():
    # Verify that autoimport and tab completion work in IPython console, when
    # started independently.
    # Start "IPython kernel".
    with IPythonKernelCtx() as kernel:
        # Start a separate "ipython console --existing kernel-1234.json".
        ipython("""
            In [1]: import pyflyby; pyflyby.enable_auto_importer()
            In [2]: b64deco\tde('bGVndW1l')
            [PYFLYBY] from base64 import b64decode
            Out[2]: b'legume'
        """, args=['console'], kernel=kernel)


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_ipython_kernel_console_multiple_existing_1():
    # Verify that autoimport and tab completion work in IPython console, when
    # the auto importer is enabled from a different console.
    # Start "IPython kernel".
    with IPythonKernelCtx() as kernel:
        # Start a separate "ipython console --existing kernel-1234.json".
        # Verify that the auto importer isn't enabled yet.
        ipython(
            """
            In [1]: b64decode('x')
            ---------------------------------------------------------------------------
            NameError                                 Traceback (most recent call last)
            ... in ...
            NameError: name 'b64decode' is not defined
        """,
            args=["console"],
            kernel=kernel,
        )
        # Enable the auto importer.
        ipython("""
            In [2]: import pyflyby; pyflyby.enable_auto_importer()
        """, args=['console'], kernel=kernel)
        # Verify that the auto importer and tab completion work.
        ipython("""
            In [3]: b64deco\tde('YWxtb25k')
            [PYFLYBY] from base64 import b64decode
            Out[3]: b'almond'
        """, args=['console'], kernel=kernel)


@pytest.mark.skip(reason="hangs")
@retry
def test_ipython_notebook_basic_1():
    with IPythonNotebookCtx() as kernel:
        ipython(
            # Verify that the auto importer isn't enabled yet.
            """
            In [1]: 3+4
            Out[1]: 7
            In [2]: 33+44
            Out[2]: 77
            """, args=['console'], kernel=kernel)

@pytest.mark.skip(
    reason="Always hang, need to investigate",
)
def test_ipython_notebook_1():
    with IPythonNotebookCtx() as kernel:
        # 1. Verify that the auto importer isn't enabled yet.
        # 2. Enable the auto importer.
        # 3. Verify that the auto importer and tab completion work.
        ipython(
            """
            In [1]: b64decode('x')
            ---------------------------------------------------------------------------
            NameError                                 Traceback (most recent call last)
            ... in ...
            NameError: name 'b64decode' is not defined
            In [2]: import pyflyby; pyflyby.enable_auto_importer()
            In [3]: b64deco\tde('aGF6ZWxudXQ=')
            [PYFLYBY] from base64 import b64decode
            Out[3]: b'hazelnut'
            """,
            args=["console"],
            kernel=kernel,
        )


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_ipython_notebook_reconnect_1():
    # Verify that we can reconnect to the same kernel, and pyflyby is still
    # enabled.
    with IPythonNotebookCtx() as kernel:
        # Verify that the auto importer isn't enabled yet.
        ipython(
            """
            In [1]: b64decode('x')
            ---------------------------------------------------------------------------
            NameError                                 Traceback (most recent call last)
            ... in ...
            NameError: name 'b64decode' is not defined
        """,
            args=["console"],
            kernel=kernel,
        )
        # Enable the auto importer.
        ipython(
        """
            In [2]: import pyflyby; pyflyby.enable_auto_importer()
        """, args=['console'], kernel=kernel)
        # Verify that the auto importer and tab completion work.
        ipython("""
            In [3]: b64deco\tde('aGF6ZWxudXQ=')
            [PYFLYBY] from base64 import b64decode
            Out[3]: b'hazelnut'
        """, args=['console'], kernel=kernel)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_py_interactive_1():
    # Verify that 'py' enables pyflyby autoimporter at start.
    ipython("""
        In [1]: b64deco\tde('cGlzdGFjaGlv')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'pistachio'
    """, prog="py")


@retry
def test_py_i_interactive_1(tmp):
    # Test that 'py -i' initializes IPython before running the commandline
    # code.
    # (The converse is tested by test_py.py:test_no_ipython_for_eval_1.)
    writetext(tmp.dir / "m32622167.py", """
        import pyflyby
        ipython_app = pyflyby._interactive._get_ipython_app()
    """)
    ipython("""
        In [1]: bool(m32622167.ipython_app)
        Out[1]: True
    """, prog="py", args=['-i', 'import m32622167'], PYTHONPATH=tmp.dir)


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_py_console_1():
    # Verify that 'py console' works.
    ipython("""
        In [1]: b64deco\tde('d2FsbnV0')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'walnut'
    """, prog="py", args=['console'])


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_py_kernel_1():
    # Verify that 'py kernel' works.
    with IPythonKernelCtx(prog="py") as kernel:
        # Run ipython console.  Note that we don't need to use prog='py' here,
        # as the autoimport & completion is a property of the kernel.
        ipython("""
            In [1]: b64deco\tde('bWFjYWRhbWlh')
            [PYFLYBY] from base64 import b64decode
            Out[1]: b'macadamia'
        """, args=['console'], kernel=kernel)


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_py_console_existing_1():
    # Verify that 'py console' works as usual (no extra functionality
    # expected over regular ipython console, but just check that it still
    # works normally).
    with IPythonKernelCtx() as kernel:
        ipython(
            """
            In [1]: b64decode('x')
            ---------------------------------------------------------------------------
            NameError                                 Traceback (most recent call last)
            ... in ...
            NameError: name 'b64decode' is not defined
        """,
            prog="py",
            args=["console"],
            kernel=kernel,
        )


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_py_notebook_1():
    with IPythonNotebookCtx(prog="py") as kernel:
        # Verify that the auto importer and tab completion work.
        ipython("""
            In [1]: b64deco\tde('Y2FzaGV3')
            [PYFLYBY] from base64 import b64decode
            Out[1]: b'cashew'
        """, args=['console'], kernel=kernel)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_py_disable_1():
    # Verify that when using 'py', we can disable the autoimporter, and
    # also re-enable it.
    ipython(
        """
        In [1]: b64deco\tde('aGlja29yeQ==')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'hickory'
        In [2]: pyflyby.disable_auto_importer()
        [PYFLYBY] import pyflyby
        In [3]: b64encode(b'x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64encode' is not defined
        In [4]: b64decode('bW9ja2VybnV0')
        Out[4]: b'mockernut'
        In [5]: pyflyby.enable_auto_importer()
        In [6]: b64encode(b'pecan')
        [PYFLYBY] from base64 import b64encode
        Out[6]: b'cGVjYW4='
    """,
        prog="py",
    )


def _install_load_ext_pyflyby_in_config(ipython_dir):
    with open(str(ipython_dir/"profile_default/ipython_config.py"), 'a') as f:
        print('c.InteractiveShellApp.extensions.append("pyflyby")', file=f)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_installed_in_config_ipython_cmdline_1(tmp):
    # Verify that autoimport works in 'ipython' when pyflyby is installed in
    # ipython_config.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython("""
        In [1]: b64deco\tde('bWFwbGU=')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'maple'
    """, ipython_dir=tmp.ipython_dir)
    # Double-check that we only modified tmp.ipython_dir.
    ipython(
        """
        In [1]: b64decode('x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64decode' is not defined
    """
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_installed_in_config_redundant_1(tmp):
    # Verify that redundant installations are fine.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython("""
        In [1]: b64deco\tde('bWFwbGU=')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'maple'
    """, ipython_dir=tmp.ipython_dir)
    # Double-check that we only modified tmp.ipython_dir.
    ipython(
        """
        In [1]: b64decode('x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64decode' is not defined
    """
    )


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_installed_in_config_ipython_console_1(tmp):
    # Verify that autoimport works in 'ipython console' when pyflyby is
    # installed in ipython_config.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython("""
        In [1]: b64deco\tde('c3BydWNl')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'spruce'
    """, args=['console'], ipython_dir=tmp.ipython_dir)


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_installed_in_config_ipython_kernel_1(tmp):
    # Verify that autoimport works in 'ipython kernel' when pyflyby is
    # installed in ipython_config.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    with IPythonKernelCtx(ipython_dir=tmp.ipython_dir) as kernel:
        ipython("""
            In [1]: b64deco\tde('b2Fr')
            [PYFLYBY] from base64 import b64decode
            Out[1]: b'oak'
        """, args=['console'], kernel=kernel)


@pytest.mark.skip(reason='fail on python 3')
@retry
def test_installed_in_config_ipython_notebook_1(tmp):
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    with IPythonNotebookCtx(ipython_dir=tmp.ipython_dir) as kernel:
        ipython("""
            In [1]: b64deco\tde('c3ljYW1vcmU=')
            [PYFLYBY] from base64 import b64decode
            Out[1]: b'sycamore'
        """, args=['console'], kernel=kernel)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_installed_in_config_disable_1(tmp):
    # Verify that when we've installed, we can still disable at run-time, and
    # also re-enable.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython(
        """
        In [1]: b64deco\tde('cGluZQ==')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'pine'
        In [2]: pyflyby.disable_auto_importer()
        [PYFLYBY] import pyflyby
        In [3]: b64encode(b'x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64encode' is not defined
        In [4]: b64decode('d2lsbG93')
        Out[4]: b'willow'
        In [5]: pyflyby.enable_auto_importer()
        In [6]: b64encode(b'elm')
        [PYFLYBY] from base64 import b64encode
        Out[6]: b'ZWxt'
    """,
        ipython_dir=tmp.ipython_dir,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_installed_in_config_enable_noop_1(tmp):
    # Verify that manually calling enable_auto_importer() is a no-op if we've
    # installed pyflyby in ipython_config.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython(
        """
        In [1]: pyflyby.enable_auto_importer()
        [PYFLYBY] import pyflyby
        In [2]: b64deco\tde('Y2hlcnJ5')
        [PYFLYBY] from base64 import b64decode
        Out[2]: b'cherry'
        In [3]: pyflyby.disable_auto_importer()
        In [4]: b64encode(b'x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64encode' is not defined
        In [5]: b64decode('YmlyY2g=')
        Out[5]: b'birch'
        In [6]: pyflyby.enable_auto_importer()
        In [7]: b64encode(b'fir')
        [PYFLYBY] from base64 import b64encode
        Out[7]: b'Zmly'
    """,
        ipython_dir=tmp.ipython_dir,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_installed_in_config_ipython_py_1(tmp):
    # Verify that installation in ipython_config and 'py' are compatible.
    _install_load_ext_pyflyby_in_config(tmp.ipython_dir)
    ipython(
        """
        In [1]: b64deco\tde('YmFzc3dvb2Q=')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'basswood'
        In [2]: pyflyby.disable_auto_importer()
        [PYFLYBY] import pyflyby
        In [3]: b64encode(b'x')
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ... in ...
        NameError: name 'b64encode' is not defined
        In [4]: b64decode('YnV0dGVybnV0')
        Out[4]: b'butternut'
        In [5]: pyflyby.enable_auto_importer()
        In [6]: b64encode(b'larch')
        [PYFLYBY] from base64 import b64encode
        Out[6]: b'bGFyY2g='
    """,
        prog="py",
        ipython_dir=tmp.ipython_dir,
    )


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_manual_install_profile_startup_1(tmp):
    # Test that manually installing to the startup folder works.
    writetext(tmp.ipython_dir/"profile_default/startup/foo.py", """
        __import__("pyflyby").enable_auto_importer()
    """)
    ipython("""
        In [1]: b64deco\tde('ZG92ZQ==')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'dove'
    """, ipython_dir=tmp.ipython_dir)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_manual_install_ipython_config_direct_1(tmp):
    # Verify that manually installing in ipython_config.py works when enabling
    # at top level.
    writetext(tmp.ipython_dir/"profile_default/ipython_config.py", """
        __import__("pyflyby").enable_auto_importer()
    """, mode='a')
    ipython("""
        In [1]: b64deco\tde('aHVtbWluZ2JpcmQ=')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'hummingbird'
    """, ipython_dir=tmp.ipython_dir)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_manual_install_exec_lines_1(tmp):
    writetext(tmp.ipython_dir/"profile_default/ipython_config.py", """
        c = get_config()
        c.InteractiveShellApp.exec_lines = [
            '__import__("pyflyby").enable_auto_importer()',
        ]
    """, mode='a')
    ipython("""
        In [1]: b64deco\tde('c2VhZ3VsbA==')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'seagull'
    """, ipython_dir=tmp.ipython_dir)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_manual_install_exec_files_1(tmp):
    writetext(tmp.file, """
        import pyflyby
        pyflyby.enable_auto_importer()
    """)
    writetext(tmp.ipython_dir/"profile_default/ipython_config.py", """
        c = get_config()
        c.InteractiveShellApp.exec_files = [%r]
    """ % (str(tmp.file),), mode='a')
    ipython("""
        In [1]: b64deco\tde('Y3Vja29v')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'cuckoo'
    """, ipython_dir=tmp.ipython_dir)





@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_cmdline_enable_c_i_1(tmp):
    ipython("""
        In [1]: b64deco\tde('Zm94aG91bmQ=')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'foxhound'
    """, args=['-c', 'import pyflyby; pyflyby.enable_auto_importer()', '-i'])


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
def test_cmdline_enable_code_to_run_i_1(tmp):
    ipython("""
        In [1]: b64deco\tde('cm90dHdlaWxlcg==')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'rottweiler'
    """, args=['--InteractiveShellApp.code_to_run='
               'import pyflyby; pyflyby.enable_auto_importer()', '-i'])


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_cmdline_enable_exec_lines_1(tmp):
    ipython("""
        In [1]: b64deco\tde('cG9vZGxl')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'poodle'
    """, args=[
        '--InteractiveShellApp.exec_lines='
        '''["__import__('pyflyby').enable_auto_importer()"]'''])


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
def test_cmdline_enable_exec_files_1(tmp):
    writetext(tmp.file, """
        import pyflyby
        pyflyby.enable_auto_importer()
    """)
    ipython("""
        In [1]: b64deco\tde('Y3Vja29v')
        [PYFLYBY] from base64 import b64decode
        Out[1]: b'cuckoo'
    """, args=[
        '--InteractiveShellApp.exec_files=[%r]' % (str(tmp.file),)])


@retry
def test_debug_baseline_1(frontend):
    # Verify that we can test ipdb without any pyflyby involved.
    ipython("""
        In [1]: 82318215/0
        ....
        ZeroDivisionError: ...
        In [2]: %debug
        ....
        ipdb> p 43405728 + 69642968
        113048696
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_without_autoimport_1(frontend):
    # Verify that without autoimport, we get a NameError.
    ipython("""
        In [1]: 70506357/0
        ....
        ZeroDivisionError: ...
        In [2]: %debug
        ....
        ipdb> p b64decode("QXVkdWJvbg==")
        *** NameError: name 'b64decode' is not defined
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_p_1(frontend):
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 17839239/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> p b64decode("S2Vuc2luZ3Rvbg==")
        [PYFLYBY] from base64 import b64decode
        b'Kensington'
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_pp_1(frontend):
    # Verify that auto importing works with "pp foo".
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 87484355/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> p b64decode("R2FyZGVu")
        [PYFLYBY] from base64 import b64decode
        b'Garden'
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_default_1(frontend):
    # Verify that auto importing works with "foo(...)".
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 41594069/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> b64decode("UHJvc3BlY3Q=")
        [PYFLYBY] from base64 import b64decode
        b'Prospect'
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_print_1(frontend):
    # Verify that auto importing works with "print foo".  (This is executed as
    # a statement; a special case of "default".)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 4046029/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> if 1: print(b64decode("TW9udGdvbWVyeQ==").decode('utf-8'))
        [PYFLYBY] from base64 import b64decode
        Montgomery
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_bang_default_1(frontend):
    # Verify that "!blah" works with auto importing.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 66783474/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> !q = b64decode("SGF3dGhvcm5l")
        [PYFLYBY] from base64 import b64decode
        ipdb> !q
        b'Hawthorne'
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_postmortem_auto_import_1(frontend):
    # Verify that %debug postmortem mode works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def foo(x, y):
           ...:     return x / y
           ...:
        In [3]: foo("Bowcraft", "Mountain")
        ---------------------------------------------------------------------------
        TypeError                                 Traceback (most recent call last)
        ....
        TypeError: unsupported operand type(s) for /: 'str' and 'str'
        In [4]: %debug
        ....
        ipdb> print(x + b64decode("QA==").decode('utf-8') + y)
        [PYFLYBY] from base64 import b64decode
        Bowcraft@Mountain
        ipdb> q
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
def test_debug_tab_completion_db_1(frontend):
    # Verify that tab completion from database works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 90383951/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> print(b64dec\tode("R2FyZmllbGQ=").decode('utf-8'))
        [PYFLYBY] from base64 import b64decode
        Garfield
        ipdb> q
    """, frontend=frontend)


@pytest.mark.skipif(is_free_threaded, reason='stderr/out and completion interleaving on 3.14t')
@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
def test_debug_tab_completion_module_1(frontend, tmp):
    # Verify that tab completion on module names works.
    writetext(tmp.dir/"thornton60097181.py", """
        randolph = 14164598
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 53418403/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> thornton60097\t181.rando\t
        ipdb> thornton60097181.rando\x06
        [PYFLYBY] import thornton60097181
        lph
        14164598
        ipdb> q
    """, PYTHONPATH=tmp.dir, frontend=frontend)


@pytest.mark.skipif(is_free_threaded, reason='stderr/out and completion interleaving on 3.14t')
@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_debug_tab_completion_multiple_1(frontend, tmp):
    # Verify that tab completion with ambiguous names works.
    writetext(tmp.dir/"sturbridge9088333.py", """
        nebula_41695458 = 1
        nebula_10983840 = 2
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 61764525/0
        ....
        ZeroDivisionError: ...
        In [3]: %debug
        ....
        ipdb> sturbridge9088333.nebula_\t
        ipdb> sturbridge9088333.nebula_
        .nebula_10983840 .nebula_41695458
        ipdb> sturbridge9088333.nebula_
        [PYFLYBY] import sturbridge9088333
        *** AttributeError: module 'sturbridge9088333' has no attribute 'nebula_'
        ipdb> q
    """, PYTHONPATH=tmp.dir, frontend=frontend)


@pytest.mark.skipif(is_free_threaded, reason='stderr/out and completion interleaving on 3.14t')
@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_debug_postmortem_tab_completion_1(frontend):
    # Verify that tab completion in %debug postmortem mode works.
    template = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def foo(x, y):
           ...:     return x / y
           ...:
        In [3]: foo("Camden", "Hopkinson")
        ---------------------------------------------------------------------------
        TypeError                                 Traceback (most recent call last)
        ....
        TypeError: unsupported operand type(s) for /: 'str' and 'str'
        In [4]: %debug
        ....
        ipdb> func = base64.b64d\t{0}
        ipdb> print(x + func("Lw==").decode('utf-8') + y)
        Camden/Hopkinson
        ipdb> q
    """
    scenario_a = """
        ipdb> func = base64.b64d\x06
        [PYFLYBY] import base64
        ecode"""
    scenario_b = """
        ipdb> func = base64.b64decode
        [PYFLYBY] import base64"""
    try:
        ipython(template.format(scenario_a), frontend=frontend)
    except pytest.fail.Exception:
        ipython(template.format(scenario_b), frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_debug_namespace_1_py3(frontend):
    # Verify that autoimporting and tab completion happen in the local
    # namespace.
    # In this example, in the local namespace, 'base64' is a variable (which
    # is a string), and shouldn't refer to the global 'base64'.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def foo(x, base64):
           ...:     return x / base64
           ...:
        In [3]: foo("Lexington", "atlantic")
        ---------------------------------------------------------------------------
        TypeError                                 Traceback (most recent call last)
        ....
        TypeError: unsupported operand type(s) for /: 'str' and 'str'
        In [4]: %debug
        ....
        ipdb> print(base64.cap\titalize() + b64deco\tde("UGFjaWZpYw==").decode('utf-8'))
        [PYFLYBY] from base64 import b64decode
        AtlanticPacific
        ipdb> p b64deco\tde("Q29udGluZW50YWw=")
        b'Continental'
        ipdb> q
        [PYFLYBY] import base64
        In [5]: base64.b64de\t
        In [5]: base64.b64decode("SGlsbA==") + b64deco\tde("TGFrZQ==")
        [PYFLYBY] from base64 import b64decode
        Out[5]: b'HillLake'
    """, frontend=frontend)


@pytest.mark.skipif(_SUPPORTS_TAB_AUTO_IMPORT, reason='Autoimport on Tab requires IPython 9.3+')
@retry
def test_debug_second_1(frontend):
    # Verify that a second postmortem debug of the same function behaves as
    # expected.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def foo(x, y):
           ...:     return x / y
           ...:
        In [3]: foo("Huron", "Osage")
        ---------------------------------------------------------------------------
        TypeError                                 Traceback (most recent call last)
        ....
        TypeError: unsupported operand type(s) for /: 'str' and 'str'
        In [4]: %debug
        ....
        ipdb> b64deco\tde("Sm9zZXBo")
        [PYFLYBY] from base64 import b64decode
        b'Joseph'
        ipdb> b64deco\tde("U2VtaW5vbGU=")
        b'Seminole'
        ipdb> q
        In [5]: foo("Quince", "Lilac")
        ---------------------------------------------------------------------------
        TypeError                                 Traceback (most recent call last)
        ....
        TypeError: unsupported operand type(s) for /: 'str' and 'str'
        In [6]: %debug
        ....
        ipdb> b64deco\tde("Q3JvY3Vz")
        [PYFLYBY] from base64 import b64decode
        b'Crocus'
        ipdb> q
    """, frontend=frontend)


@retry
def test_debug_auto_import_string_1(frontend):
    # Verify that auto importing works inside the debugger after running
    # "%debug <string>".
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %debug 44968817
        NOTE: Enter 'c' at the ipdb>  prompt to continue execution.
        > <string>(1)<module>()
        ipdb> p b64decode("TGluc2xleQ==")
        [PYFLYBY] from base64 import b64decode
        b'Linsley'
        ipdb> q
    """, frontend=frontend)


def test_debug_auto_import_of_string_1(frontend, tmp):
    # Verify that auto importing works for the string to be debugged.
    writetext(tmp.dir/"peekskill43666930.py", """
        def hollow(x):
            print(x * 2)
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %debug peekskill43666930.hollow(67658141)
        [PYFLYBY] import peekskill43666930
        NOTE: Enter 'c' at the ipdb>  prompt to continue execution.
        > <string>(1)<module>()
        ipdb> c
        135316282
    """, PYTHONPATH=tmp.dir, frontend=frontend)


@retry
def test_debug_auto_import_statement_step_1(frontend, tmp):
    # Verify that step functionality isn't broken.
    writetext(tmp.dir/"taconic72383428.py", """
        def pudding(x):
            y = x * 5
            print(y)
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %debug taconic72383428.pudding(48364325)
        [PYFLYBY] import taconic72383428
        NOTE: Enter 'c' at the ipdb>  prompt to continue execution.
        > <string>(1)<module>()
        ipdb> s
        ....
        ipdb> n
        ....
        ipdb> print(x)
        48364325
        ipdb> x = os.path.sep
        [PYFLYBY] import os.path
        ipdb> c
        /////
    """, PYTHONPATH=tmp.dir, frontend=frontend)

# TODO: test embedded mode.  Something like this:
#         >>> sys = 86176104
#         >>> import IPython
#         >>> IPython.embed()
#         ....
#         In [1]: import pyflyby
#         In [2]: pyflyby.enable_auto_importer()
#         In [3]: b64decode("cG93bmFs")
#         [PYFLYBY] from base64 import b64decode
#         Out[3]: b'pownal'
#         In [4]: sys
#         Out[4]: 86176104
#         In [5]: exit()
#         >>> b64decode("...")
#         ...
#         >>> b64encode(b"...")
#         NameError: ...

# TODO: add tests for when IPython is not installed.  either using a tox
# environment, or using a PYTHONPATH that shadows IPython with something
# unimportable.


@pytest.mark.skipif(
    _IPYTHON_VERSION < (7, 0),
    reason="old IPython and Python won't work with breakpoint()",
)
@retry
def test_breakpoint_IOStream_broken():
    # Verify that step functionality isn't broken.
    if sys.version_info >= (3, 14):
        ipython(
            """
            In [1]: breakpoint()
            ...
            > <ipython-input>(1)<module>()
            ipdb> c
        """,
            frontend="prompt_toolkit",
        )
    elif sys.version_info >= (3, 13):
        ipython(
            """
            In [1]: breakpoint()
            > <ipython-input>(1)<module>()
            ipdb> c
        """,
            frontend="prompt_toolkit",
        )
    else:
        # The `__call__` in trace below is expected because
        # the next instruction is IPython's `displayhook`
        # at `IPython.core.displayhook.DisplayHook.__call__`.
        ipython(
            '''
            In [1]: breakpoint()
            --Call--
            > ...
                ...
                ...
            --> ...     def __call__(self, result=None):
                ...         """Printing with history cache management.
                ...
            ipdb> c
        ''',
            frontend='prompt_toolkit',
        )
