# pyflyby/test_interactive.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import IPython
import atexit
from   cStringIO                import StringIO
import difflib
import inspect
import os
import pexpect
import pytest
import random
import re
import readline
from   shutil                   import rmtree
import signal
import sys
from   tempfile                 import mkdtemp, mkstemp
from   textwrap                 import dedent

import pyflyby
from   pyflyby._file            import Filename
from   pyflyby._util            import EnvVarCtx, cached_attribute, memoize


# TODO: test IPython kernel (closest thing to testing Notebook)


def assert_fail():
    """
    Assert that pytest.fail() is called in the context.  Used to self-test.
    """
    import _pytest
    return pytest.raises(_pytest.runner.Failed)


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
        The file is NOT under C{self.dir}.
        """
        return self.new_tempfile()

    def new_tempdir(self):
        d = mkdtemp(prefix="pyflyby_test_", suffix=".tmp")
        self._request.addfinalizer(lambda: rmtree(d))
        return Filename(d)

    def new_tempfile(self, dir=None):
        fd, f = mkstemp(prefix="pyflyby_test_", suffix=".tmp", dir=dir)
        os.close(fd)
        self._request.addfinalizer(lambda: os.unlink(f))
        return Filename(f)


def writetext(filename, text):
    text = dedent(text)
    filename = Filename(filename)
    with open(str(filename), 'w') as f:
        f.write(text)
    return filename


def assert_match(result, expected):
    """
    Check that C{result} matches C{expected}.
    C{expected} is a pattern where
      * "..." (three dots) matches any text (but not newline), and
      * "...." (four dots) matches any text (including newline).
    """
    __tracebackhide__ = True
    expected = dedent(expected).strip()
    result = '\n'.join(line.rstrip() for line in result.splitlines())
    result = result.strip()
    parts = expected.split("...")
    regexp_parts = [re.escape(parts[0])]
    for s in parts[1:]:
        if re.match(":( |$)", s, re.M) and regexp_parts[-1] == "  ":
            # Treat "\n  ...: " specially; don't make it a glob.
            regexp_parts.append("...")
            regexp_parts.append(re.escape(s))
        elif s.startswith("."):
            regexp_parts.append("(?:.|\n)*")
            regexp_parts.append(re.escape(s[1:]))
        else:
            regexp_parts.append(".*")
            regexp_parts.append(re.escape(s))
    regexp_parts.append("$")
    regexp = "".join(regexp_parts)

    if _IPYTHON_VERSION < (0, 11):
        # IPython 0.10 prompt counts are buggy, e.g. %time increments by 2.
        # Ignore prompt numbers and extra newlines before the output prompt.
        regexp = re.sub(re.compile(r"^In\\? \\\[[0-9]+\\\]", re.M),
                        r"In \[[0-9]+\]", regexp)
        regexp = re.sub(re.compile(r"^Out\\\[[0-9]+\\\]", re.M),
                        r"\n?Out\[[0-9]+\]", regexp)
    regexp = re.compile(regexp)
    if not regexp.match(result):
        msg = []
        msg.append("Expected:")
        msg.extend("     %s"%line for line in expected.splitlines())
        msg.append("Result:")
        msg.extend("     %s"%line for line in result.splitlines())
        msg.append("Diff:")
        msg.extend("   %s"%line for line in difflib.ndiff(
            expected.splitlines(), result.splitlines()))
        msg = "\n".join(msg)
        pytest.fail(msg)


def parse_template(template):
    template = dedent(template).strip()
    input = []
    expected = []
    pattern = re.compile("^(?:In \[[0-9]+\]|   [.][.][.]+):(?: |$)", re.M)
    while template:
        m = pattern.search(template)
        if not m:
            expected.append(template)
            break
        expline = m.group(0)
        expected.append(template[:m.end()])
        template = template[m.end():]
        while template and not template.startswith("\n"):
            # We're in the input part of a template.  Get input up to tab or
            # end of line.
            m = re.match(re.compile("(.*?)(\t|$)", re.M), template)
            input.append(m.group(1))
            expline += m.group(1)
            expected.append(m.group(1))
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
            if template.startswith("\n"):
                rep = template.rfind(expline)
                assert rep >= 0
                repend = rep + len(expline)
                expected.append(template[:repend])
                template = template[repend:]
            # Assume that all subsequent symbol characters (alphanumeric
            # and underscore) in the template represent tab completion
            # output.
            m = re.match("[a-zA-Z0-9_]+", template)
            if m:
                expline += m.group(0)
                expected.append(m.group(0))
                template = template[m.end():]
                # Allow \x06 in the template to be a special character meaning
                # "end of tab completion output".
            if template.startswith("\x06"):
                template = template[1:]
        input.append("\n")
    input = "".join(input)
    expected = "".join(expected)
    return input, expected


def test_selftest_parse_template_1():
    template = """
        In [1]: hello
        there
        world
        In [2]: foo
           ...: bar
           ...:
        baz
    """
    input, expected = parse_template(template)
    assert input == "hello\nfoo\nbar\n\n"
    assert expected == (
        "In [1]: hello\nthere\nworld\n"
        "In [2]: foo\n   ...: bar\n   ...:\nbaz")


def test_selftest_parse_template_tab_punctuation_1():
    template = """
        In [1]: hello\t_there(3)
        goodbye
    """
    input, expected = parse_template(template)
    assert input == "hello\t(3)\n"
    assert expected == ("In [1]: hello_there(3)\ngoodbye")


def test_selftest_parse_template_tab_newline_():
    template = """
        In [1]: hello_\tthere
        goodbye
    """
    input, expected = parse_template(template)
    assert input == "hello_\t\n"
    assert expected == ("In [1]: hello_there\ngoodbye")


def test_selftest_parse_template_tab_continue_1():
    template = """
        In [1]: hello\t_the\x06re(3)
        goodbye
    """
    input, expected = parse_template(template)
    assert input == "hello\tre(3)\n"
    assert expected == ("In [1]: hello_there(3)\ngoodbye")


def test_selftest_parse_template_tab_log_1():
    template = """
        In [1]: hello\t
        bonjour
        In [1]: hello
        hallo
        In [1]: hello_there(5)
        goodbye
    """
    input, expected = parse_template(template)
    assert input == "hello\t(5)\n"
    assert expected == (
        "In [1]: hello\n"
        "bonjour\n"
        "In [1]: hello\n"
        "hallo\n"
        "In [1]: hello_there(5)\n"
        "goodbye")


def test_selftest_assert_match_1():
    expected = """
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
    """)
    assert_match(result, expected)


def test_selftest_assert_match_2():
    result = """
        hello
        1...2
        there
    """
    expected = """

      hello
      14712047
      602
      there

    """
    with assert_fail():
        assert_match(result, expected)


def remove_ansi_escapes(s):
    s = re.sub("\x1B\[[?]?[0-9;]*[a-zA-Z]", "", s)
    s = re.sub("[\x01\x02]", "", s)
    return s


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



_IPYTHON_VERSION = _parse_version(IPython.__version__)

_IPYTHON_PROMPT1 = "\nIn \[[0-9]+\]: "
_IPYTHON_PROMPT2 = "\n   [.][.][.]+: "
_IPYTHON_PROMPTS = [_IPYTHON_PROMPT1, _IPYTHON_PROMPT2]


@memoize
def _extra_readline_pythonpath_dirs():
    """
    Return a path to use as an extra PYTHONPATH component in order to get GNU
    readline to work.
    """
    if sys.platform != "darwin":
        return ()
    # On Darwin, we need a hack to make sure IPython gets GNU readline instead
    # of libedit.
    if "libedit" not in readline.__doc__:
        return ()
    dir = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    atexit.register(lambda: rmtree(dir))
    import site
    sitepackages = os.path.join(os.path.dirname(site.__file__), "site-packages")
    readline_fn = os.path.abspath(os.path.join(sitepackages, "readline.so"))
    if not os.path.isfile(readline_fn):
        raise ValueError("Couldn't find readline")
    os.symlink(readline_fn, os.path.join(dir, "readline.so"))
    return (dir,)


def _build_pythonpath(PYTHONPATH):
    """
    Build PYTHONPATH value to use.

    @rtype:
      C{str}
    """
    pypath = [os.path.dirname(os.path.dirname(pyflyby.__file__))]
    pypath += _extra_readline_pythonpath_dirs()
    if isinstance(PYTHONPATH, (Filename, basestring)):
        PYTHONPATH = [PYTHONPATH]
    PYTHONPATH = [str(Filename(d)) for d in PYTHONPATH]
    pypath += PYTHONPATH
    pypath += os.environ["PYTHONPATH"].split(":")
    return ":".join(pypath)


def _build_ipython_cmd(ipython_dir, autocall=False):
    """
    Prepare the command to run IPython.
    """
    ipython_dir = Filename(ipython_dir)
    cmd = []
    if '/.tox/' in sys.prefix:
        # Get the ipython from our (tox virtualenv) path.
        cmd += [os.path.join(os.path.dirname(sys.executable), "ipython")]
    else:
        cmd += ["ipython"]
    # Construct IPython arguments based on version.
    if _IPYTHON_VERSION >= (0, 11):
        cmd += [
            "--ipython-dir=%s" % (ipython_dir,),
            "--no-confirm-exit",
            "--no-banner",
            "--quiet",
            "--colors=NoColor",
            "--no-term-title",
            "--no-autoindent",
        ]
        if autocall:
            cmd += ["--autocall=1"]
    elif _IPYTHON_VERSION >= (0, 10):
        cmd += [
            "-ipythondir=%s" % (ipython_dir,),
            "-noconfirm_exit",
            "-nomessages",
            "-nobanner",
            "-colors=NoColor",
            "-noautoindent",
        ]
        if autocall:
            cmd += ["-autocall=1"]
        writetext(ipython_dir/"ipythonrc", """
            readline_parse_and_bind tab: complete
            readline_parse_and_bind set show-all-if-ambiguous on
        """)
        writetext(ipython_dir/"ipy_user_conf.py", "")
    else:
        raise NotImplementedError("Don't know how to test IPython version %s"
                                  % (_IPYTHON_VERSION,))
    return cmd


PYFLYBY_HOME = Filename(__file__).real.dir.dir
PYFLYBY_PATH = PYFLYBY_HOME / "etc/pyflyby"


class MySpawn(pexpect.spawn):
    def setwinsize(self, rows, cols):
        """
        Override the window size in the child terminal.

        We need to do this after the forkpty but before the child IPython
        process is execed.  As of pexpect version 3.3, overriding this method
        is the only way to do that.

        If we don't change the default from 80 columns, then Readline outputs
        an annoying extra " \r" after 80 characters of prompt+input.

        https://github.com/pexpect/pexpect/issues/134
        """
        super(MySpawn, self).setwinsize(100, 900)


def spawn_ipython(input, autocall=False,
                  PYTHONPATH=[],
                  PYFLYBY_PATH=PYFLYBY_PATH,
                  PYFLYBY_LOG_LEVEL=""):
    """
    Spawn IPython in a pty subprocess.  Send it input and expect output.
    """
    if hasattr(PYFLYBY_PATH, "write"):
        PYFLYBY_PATH = PYFLYBY_PATH.name
    PYFLYBY_PATH = str(Filename(PYFLYBY_PATH))
    # Create a temporary directory which we'll use as our IPYTHONDIR.
    ipython_dir = mkdtemp(prefix="pyflyby_test_ipython_", suffix=".tmp")
    child = None
    try:
        # Prepare environment variables.
        env = {}
        env["PYFLYBY_PATH"]      = PYFLYBY_PATH
        env["PYFLYBY_LOG_LEVEL"] = PYFLYBY_LOG_LEVEL
        env["PYTHONPATH"]        = _build_pythonpath(PYTHONPATH)
        env["PYTHONSTARTUP"]     = ""
        cmd = _build_ipython_cmd(ipython_dir, autocall=autocall)
        # Spawn IPython.
        with EnvVarCtx(**env):
            child = MySpawn(cmd[0], cmd[1:], echo=True, timeout=5.0)
        # Log output to a StringIO.  Note that we use "logfile_read", not
        # "logfile".  If we used logfile, that would double-log the input
        # commands, since we used echo=True.  (Using logfile=StringIO and
        # echo=False works for most inputs, but doesn't work for things like
        # tab completion output.)
        output = StringIO()
        child.logfile_read = output
        # Don't delay 0.05s before sending.
        child.delaybeforesend = 0.0
        # Canonicalize input lines.
        input = dedent(input)
        input = re.sub("^\n+", "", input)
        input = re.sub("\n+$", "", input)
        input += "\nexit()\n"
        lines = input.splitlines(False)
        # Loop over lines.
        for line in lines:
            # Wait for the "In [N]:" prompt.
            child.expect(_IPYTHON_PROMPTS)
            while line:
                left, tab, right = line.partition("\t")
                # Send the input (up to tab or newline).
                child.send(left)
                # Check that the client IPython gets the input.
                child.expect_exact(left)
                if tab:
                    # Send the tab.
                    child.send(tab)
                    # Wait for response to tab.
                    _wait_nonce(child)
                line = right
            child.send("\n")
        # We're finished sending input commands.  Wait for process to
        # complete.
        child.expect(pexpect.EOF)
    except (pexpect.TIMEOUT, pexpect.EOF):
        print "Timed out."
        print "Output so far:"
        result = _clean_ipython_output(output.getvalue())
        print ''.join("    %s\n"%line for line in result.splitlines())
        raise
    finally:
        # Clean up.
        if child is not None and child.isalive():
            child.kill(signal.SIGKILL)
        rmtree(ipython_dir)
    result = output.getvalue()
    result = _clean_ipython_output(result)
    return result


def ipython(template, **kwargs):
    """
    Run IPython in a pty subprocess.  Send it input and expect output based on
    the template.  Assert that the result matches.
    """
    __tracebackhide__ = True
    parent_frame = inspect.currentframe().f_back
    parent_globals = parent_frame.f_globals
    parent_locals = parent_frame.f_locals
    parent_vars = dict(parent_globals, **parent_locals)
    template = dedent(template).strip()
    template = template.format(**parent_vars)
    input, expected = parse_template(template)
    # print "Input:"
    # print "".join("    %s\n"%line for line in input.splitlines())
    result = spawn_ipython(input, **kwargs)
    # print "Output:"
    # print "".join("    %s\n"%line for line in result.splitlines())
    assert_match(result, expected)


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
        nonce = "<SIG %s />" % (random.random())
        child.send(nonce)
        # Wait for the nonce.
        child.expect_exact(nonce)
        data_after_tab = child.before
        # Log what came before the nonce (but not the nonce itself).
        logfile_read.write(data_after_tab)
        # Delete the nonce we typed.  We do this one character at a time,
        # because that causes readline to output simple "\b"s instead of using
        # extra escape sequences.
        backspaces = "\b" * len(nonce)
        for bs in backspaces:
            child.send(bs)
            child.expect(bs)
    finally:
        child.logfile_read = logfile_read


def _clean_ipython_output(result):
    """Clean up IPython output."""
    # Canonicalize newlines.
    result = result.replace("\r\n", "\n")
    # Remove ANSI escape sequences.  (We already turned off IPython
    # prompt colors, but pyflyby still colorizes log output.)
    result = remove_ansi_escapes(result)
    # Make traceback output stable across IPython versions and runs.
    result = re.sub(re.compile(r"(^/.*?/)?<(ipython-input-[0-9]+-[0-9a-f]+|ipython console)>", re.M), "<ipython-input>", result)
    result = re.sub(re.compile(r"^----> .*?\n", re.M), "", result)
    # Remove "In [N]: exit()".
    result = re.sub(_IPYTHON_PROMPT1 + "exit[(][)]\n$", "", result)
    # Compress newlines.
    result = re.sub("\n\n+", "\n", result)
    return result


def test_ipython_1():
    # Test that we can run ipython and get results back.
    ipython("""
        In [1]: print 6*7
        42
        In [2]: 6*9
        Out[2]: 54
    """)


def test_ipython_2():
    with assert_fail():
        ipython("""
            In [1]: print 6*7
            42
            In [2]: 6*9
            Out[2]: 53
        """)


def test_pyflyby_file_1():
    # Verify that our test setup is getting the right pyflyby.
    f = pyflyby.__file__.replace(".pyc", ".py")
    ipython("""
        In [1]: import pyflyby
        In [2]: print pyflyby.__file__.replace(".pyc", ".py")
        {f}
    """)


def test_pyflyby_version_1():
    # Verify that our test setup is getting the right pyflyby.
    ipython("""
        In [1]: import pyflyby
        In [2]: print pyflyby.__version__
        {pyflyby.__version__}
    """)


def test_ipython_file_1():
    # Verify that our test setup is getting the right IPython.
    ipython("""
        In [1]: import IPython
        In [2]: print IPython.__file__
        {IPython.__file__}
    """)


def test_ipython_version_1():
    # Verify that our test setup is getting the right IPython.
    ipython("""
        In [1]: import IPython
        In [2]: print IPython.__version__
        {IPython.__version__}
    """)


def test_autoimport_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: '@'+b64decode('SGVsbG8=')+'@'
        [PYFLYBY] from base64 import b64decode
        Out[2]: '@Hello@'
    """)


def test_no_autoimport_1():
    # Test that without pyflyby installed, we do get NameError.  This is
    # really a test that our testing infrastructure is OK and not accidentally
    # picking up pyflyby configuration installed in a system or user config.
    ipython("""
        In [1]: '@'+b64decode('SGVsbG8=')+'@'
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64decode' is not defined
    """)


def test_autoimport_symbol_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode
        [PYFLYBY] from base64 import b64decode
        Out[2]: <function ...b64decode...>
    """)


def test_autoimport_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('SGVsbG8=')
        [PYFLYBY] from base64 import b64decode
        Hello
    """)


def test_autoimport_multiple_imports_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64encode("koala"), b64decode("a2FuZ2Fyb28=")
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] from base64 import b64encode
        a29hbGE= kangaroo
    """)


def test_autoimport_multiline_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print b64decode('dHVydGxl')
           ...:
        [PYFLYBY] from base64 import b64decode
        turtle
        In [3]: print b64decode('bGFtYQ==')
        lama
    """)


def test_autoimport_multiline_continued_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     (sys.
           ...:         stdout
           ...:             .write(
           ...:                 b64decode(
           ...:                     'bWljcm9waG9uZQ==')))
           ...:
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] import sys
        microphone
        In [3]: print b64decode('bG91ZHNwZWFrZXI=')
        loudspeaker
    """)


def test_autoimport_multiline_continued_statement_fake_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print (unknown_symbol_37320899.
           ...:         b64encode
           ...:         )
           ...:
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        ....
        NameError: name 'unknown_symbol_37320899' is not defined
        In [3]: if 1:
           ...:     print b64encode('y')
           ...:
        [PYFLYBY] from base64 import b64encode
        eQ==
        In [4]: print b64decode('YmFzZWJhbGw=')
        [PYFLYBY] from base64 import b64decode
        baseball
    """)


def test_autoimport_pyflyby_path_1(tmp):
    writetext(tmp.file, "from itertools import product\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: list(product('ab','cd'))
        [PYFLYBY] from itertools import product
        Out[2]: [('a', 'c'), ('a', 'd'), ('b', 'c'), ('b', 'd')]
        In [3]: groupby
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'groupby' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_autoimport_autocall_arg_1():
    # Verify that we can autoimport the argument of an autocall.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: str.upper b64decode('a2V5Ym9hcmQ=')
        ------> str.upper(b64decode('a2V5Ym9hcmQ='))
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'KEYBOARD'
    """, autocall=True)


def test_autoimport_autocall_function_1():
    # Verify that we can autoimport the function to autocall.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode 'bW91c2U='
        [PYFLYBY] from base64 import b64decode
        ------> b64decode('bW91c2U=')
        Out[2]: 'mouse'
    """, autocall=True)


def test_autoimport_multiple_candidates_ast_transformer_1(tmp):
    # Verify that we print out all candidate autoimports, when there are
    # multiple.
    writetext(tmp.file, """
        import foo23596267 as bar
        import foo50853429 as bar
        import foo47979882 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo23596267 as bar
        [PYFLYBY]   import foo47979882 as bar
        [PYFLYBY]   import foo50853429 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_autoimport_multiple_candidates_repeated_1(tmp):
    # Verify that we print out the candidate list for another cell.
    writetext(tmp.file, """
        import foo70603247 as bar
        import foo31703722 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo31703722 as bar
        [PYFLYBY]   import foo70603247 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
        In [3]: bar(42)
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo31703722 as bar
        [PYFLYBY]   import foo70603247 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_autoimport_multiple_candidates_multiple_in_expression_1(tmp):
    # Verify that if an expression contains multiple ambiguous imports, we
    # report each one.
    writetext(tmp.file, """
        import foo85957810 as foo
        import foo35483918 as foo
        import bar25290002 as bar
        import bar36166308 as bar
    """)
    ipython("""
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
        <ipython-input> in <module>()
        NameError: name 'foo' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_autoimport_multiple_candidates_repeated_in_expression_1(tmp):
    # Verify that if an expression contains an ambiguous import twice, we only
    # report it once.
    writetext(tmp.file, """
        import foo83958492 as bar
        import foo29432668 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar+bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo29432668 as bar
        [PYFLYBY]   import foo83958492 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
    """, PYFLYBY_PATH=tmp.file)


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


def test_autoimport_multiple_candidates_multi_joinpoint_1(tmp):
    # Verify that the autoimport menu is only printed once, even when multiple
    # joinpoints apply (autocall=>ofind and ast_importer).
    writetext(tmp.file, """
        import foo85223658 as bar
        import foo10735265 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
    """, PYFLYBY_PATH=tmp.file, autocall=True)


def test_autoimport_multiple_candidates_multi_joinpoint_repeated_1(tmp):
    # We should report the multiple candidate issue again if asked again.
    writetext(tmp.file, """
        import foo85223658 as bar
        import foo10735265 as bar
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
        In [3]: bar
        [PYFLYBY] Multiple candidate imports for bar.  Please pick one:
        [PYFLYBY]   import foo10735265 as bar
        [PYFLYBY]   import foo85223658 as bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar' is not defined
    """, PYFLYBY_PATH=tmp.file, autocall=True)


def test_complete_symbol_basic_1():
    # Verify that tab completion works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64deco\tde('eHl6enk=')
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'xyzzy'
    """)


def test_complete_symbol_multiple_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64\t
        b64decode  b64encode
        In [2]: print b64\x06decode
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """)


def test_complete_symbol_partial_multiple_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b6\t
        b64decode  b64encode
        In [2]: print b64\x06d\tecode
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """)


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
        Out[4]: 'Rubicon'
        In [5]: 'base64' in globals()
        Out[5]: False
        In [6]: 'b64decode' in globals()
        Out[6]: True
    """)


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


def test_complete_symbol_member_1():
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
        Out[2]: 'monty'
    """)


def test_complete_symbol_member_multiple_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print base64.b64\t
        [PYFLYBY] import base64
        In [2]: print base64.b64
        base64.b64decode  base64.b64encode
        In [2]: print base64.b64
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        <ipython-input> in <module>()
        AttributeError: 'module' object has no attribute 'b64'
    """)


def test_complete_symbol_member_partial_multiple_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print base64.b6\t
        [PYFLYBY] import base64
        In [2]: print base64.b6
        base64.b64decode  base64.b64encode
        In [2]: print base64.b64
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        <ipython-input> in <module>()
        AttributeError: 'module' object has no attribute 'b64'
    """)


def test_complete_symbol_import_module_as_1(tmp):
    writetext(tmp.file, "import base64 as b64\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64.b64d\t
        [PYFLYBY] import base64 as b64
        In [2]: b64.b64decode('cm9zZWJ1ZA==')
        Out[2]: 'rosebud'
    """, PYFLYBY_PATH=tmp.file)


def test_complete_symbol_statement_1():
    # Verify that tab completion in statements works.  This requires a more
    # sophisticated code path than test_complete_symbol_basic_1.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: x = b64deco\tde('SHVudGVy')
        [PYFLYBY] from base64 import b64decode
        In [3]: print x
        Hunter
    """)


def test_complete_symbol_multiline_statement_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print b64deco\tde('emVicmE=')
           ...:     print 42
           ...:
        [PYFLYBY] from base64 import b64decode
        zebra
        42
        In [3]: print b64decode('dGlnZXI=')
        tiger
    """)


def test_complete_symbol_multiline_statement_member_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print base64.b64d\t
        [PYFLYBY] import base64
           ...:     print base64.b64decode('Z2lyYWZmZQ==')
           ...:     print 42
           ...:
        giraffe
        42
        In [3]: print b64d\tecode('bGlvbg==')
        [PYFLYBY] from base64 import b64decode
        lion
    """)


def test_complete_symbol_autocall_arg_1():
    # Verify that tab completion works with autocall.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: str.upper b64deco\tde('Q2hld2JhY2Nh')
        ------> str.upper(b64decode('Q2hld2JhY2Nh'))
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'CHEWBACCA'
    """, autocall=True)


def test_complete_symbol_any_module_1(tmp):
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
    """, PYTHONPATH=tmp.dir)


def test_complete_symbol_any_module_member_1(tmp):
    # Verify that completion on members works for an arbitrary module in
    # $PYTHONPATH.
    writetext(tmp.dir/"m51145108_foo.py", """
        def f_76313558_59577191(): return 'ok'
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: m51145108_\tfoo.f_76313558_\t
        [PYFLYBY] import m51145108_foo
        In [2]: m51145108_foo.f_76313558_59577191()
        Out[2]: 'ok'
    """, PYTHONPATH=tmp.dir)


def test_complete_symbol_bad_1(tmp):
    # Verify that if we have a bad item in known imports, we complete it still.
    writetext(tmp.file, "import foo_31221052_bar\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: foo_31221052_\tbar
        [PYFLYBY] import foo_31221052_bar
        [PYFLYBY] Error attempting to 'import foo_31221052_bar': ImportError: No module named foo_31221052_bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'foo_31221052_bar' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_complete_symbol_bad_as_1(tmp):
    writetext(tmp.file, "import foo_86487172 as bar_98073069_quux\n")
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar_98073069_\tquux.asdf
        [PYFLYBY] import foo_86487172 as bar_98073069_quux
        [PYFLYBY] Error attempting to 'import foo_86487172 as bar_98073069_quux': ImportError: No module named foo_86487172
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar_98073069_quux' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_disable_reenable_autoimport_1():
    ipython("""
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: b64encode('blue')
        [PYFLYBY] from base64 import b64encode
        Out[3]: 'Ymx1ZQ=='
        In [4]: pyflyby.disable_auto_importer()
        In [5]: b64decode('cmVk')        # expect NameError since no auto importer
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64decode' is not defined
        In [6]: b64encode('green')       # should still work because already imported
        Out[6]: 'Z3JlZW4='
        In [7]: pyflyby.enable_auto_importer()
        In [8]: b64decode('eWVsbG93')    # should work now
        [PYFLYBY] from base64 import b64decode
        Out[8]: 'yellow'
    """)


def test_disable_reenable_completion_1():
    ipython("""
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: b64enco\tde('flower')
        [PYFLYBY] from base64 import b64encode
        Out[3]: 'Zmxvd2Vy'
        In [4]: pyflyby.disable_auto_importer()
        In [5]: b64deco\t('Y2xvdWQ=') # expect NameError since no auto importer
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64deco' is not defined
        In [6]: b64enco\tde('tree') # should still work because already imported
        Out[6]: 'dHJlZQ=='
        In [7]: pyflyby.enable_auto_importer()
        In [8]: b64deco\tde('Y2xvdWQ=') # should work now
        [PYFLYBY] from base64 import b64decode
        Out[8]: 'cloud'
    """)


def test_pinfo_1(tmp):
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
        Docstring:....hello from 34229186
    """, PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.file)


def test_error_during_auto_import_symbol_1(tmp):
    writetext(tmp.file, "3+")
    ipython("""
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
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_68470042' is not defined
        In [5]: unknown_symbol_76663387
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_76663387' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_error_during_auto_import_expression_1(tmp):
    writetext(tmp.file, "3+")
    ipython("""
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
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_72161870' is not defined
        In [5]: 42+unknown_symbol_48517397
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_48517397' is not defined
    """, PYFLYBY_PATH=tmp.file)


def test_error_during_completion_1(tmp):
    writetext(tmp.file, "3+")
    ipython("""
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
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_14954304_foo' is not defined
        In [5]: 200
        Out[5]: 200
        In [6]: unknown_symbol_69697066_\t\x06foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_69697066_foo' is not defined
        In [7]: 300
        Out[7]: 300
    """, PYFLYBY_PATH=tmp.file)


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
        Out[3]: 'midnight'
    """)


def test_run_1(tmp):
    # Test that %run works and autoimports.
    writetext(tmp.file, """
        print 'hello'
        print b64decode('RXVjbGlk')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        hello
        Euclid
    """)


def test_run_repeat_1(tmp):
    # Test that repeated %run works, and continues autoimporting, since we
    # start from a fresh namespace each time (since no "-i" option to %run).
    writetext(tmp.file, """
        print b64decode('Q2FudG9y')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Cantor
        In [3]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Cantor
    """)


def test_run_separate_script_namespace_1(tmp):
    # Another explicit test that we start %run from a fresh namespace
    writetext(tmp.file, """
        print b64decode('UmllbWFubg==')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('Rmlib25hY2Np')
        [PYFLYBY] from base64 import b64decode
        Fibonacci
        In [3]: run {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Riemann
    """)


def test_run_separate_script_namespace_2(tmp):
    # Another explicit test that we start %run from a fresh namespace, not
    # inheriting even explicitly defined functions.
    writetext(tmp.file, """
        print b64decode('SGlsYmVydA==')
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
    """)


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
        Out[3]: 'Fermat'
        In [4]: b64decode('TGFwbGFjZQ==')
        Out[4]: 'Laplace'
    """)


def test_run_i_auto_import_1(tmp):
    # Verify that '%run -i' works and autoimports.
    writetext(tmp.file, """
        print b64decode('RGVzY2FydGVz')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -i {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Descartes
        In [3]: print b64decode('R2F1c3M=')
        Gauss
    """)


def test_run_i_already_imported_1(tmp):
    # Verify that '%run -i' inherits the interactive namespace.
    writetext(tmp.file, """
        print b64decode(k)
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('R3JvdGhlbmRpZWNr')
        [PYFLYBY] from base64 import b64decode
        Grothendieck
        In [3]: k = 'QXJjaGltZWRlcw=='
        In [4]: run -i {tmp.file}
        Archimedes
    """)


def test_run_i_repeated_1(tmp):
    # Verify that '%run -i' affects the next namespace of the next '%run -i'.
    writetext(tmp.file, """
        print b64decode('S29sbW9nb3Jvdg==')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -i {tmp.file}
        [PYFLYBY] from base64 import b64decode
        Kolmogorov
        In [3]: run -i {tmp.file}
        Kolmogorov
    """)


def test_run_i_locally_defined_1(tmp):
    # Verify that '%run -i' can inherit interactively defined symbols.
    writetext(tmp.file, """
        print b64decode('zzz')
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def b64decode(x):
           ...:     return "Bernoulli"
           ...:
        In [3]: run -i {tmp.file}
        Bernoulli
    """)


def test_run_syntax_error_1(tmp):
    # Verify that a syntax error in a user-run script doesn't affect
    # autoimporter functionality.
    writetext(tmp.file, """
        print 'hello'
        print b64decode('UHl0aGFnb3Jhcw==')
        1 /
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        ....
        SyntaxError: invalid syntax....
        In [3]: print b64decode('Q29ud2F5')
        [PYFLYBY] from base64 import b64decode
        Conway
    """)


def test_run_name_main_1(tmp):
    # Verify that __name__ == "__main__" in a %run script.
    writetext(tmp.file, """
        print b64encode(__name__)
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run {tmp.file}
        [PYFLYBY] from base64 import b64encode
        X19tYWluX18=
    """)


def test_run_name_not_main_1(tmp):
    # Verify that __name__ == basename(filename) using '%run -n'.
    f = writetext(tmp.dir/"f81564382.py", """
        print b64encode(__name__)
    """)
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run -n {f}
        [PYFLYBY] from base64 import b64encode
        ZjgxNTY0Mzgy
    """)


def test_timeit_1():
    # Verify that %timeit works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %timeit -n 1 -r 1 b64decode('TWljaGVsYW5nZWxv')
        [PYFLYBY] from base64 import b64decode
        1 loops, best of 1: ... per loop
        In [3]: %timeit -n 1 -r 1 b64decode('RGF2aWQ=')
        1 loops, best of 1: ... per loop
    """)


def test_timeit_complete_1():
    # Verify that tab completion works with %timeit.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %timeit -n 1 -r 1 b64de\tcode('cGlsbG93')
        [PYFLYBY] from base64 import b64decode
        1 loops, best of 1: ... per loop
    """)


def test_timeit_complete_menu_1():
    # Verify that menu tab completion works with %timeit.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: timeit -n 1 -r 1 b64\t
        b64decode  b64encode
        In [2]: timeit -n 1 -r 1 b64\x06d\tecode('YmxhbmtldA==')
        [PYFLYBY] from base64 import b64decode
        1 loops, best of 1: ... per loop
    """)


def test_timeit_complete_autoimport_member_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: timeit -n 1 -r 1 base64.b6\t
        [PYFLYBY] import base64
        In [2]: timeit -n 1 -r 1 base64.b6
        base64.b64decode  base64.b64encode
        In [2]: timeit -n 1 -r 1 base64.b64\x06dec\tode('bWF0dHJlc3M=')
        1 loops, best of 1: ... per loop
    """)


def test_time_1():
    # Verify that %time autoimport works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64decode("dGVsZXBob25l")
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: 'telephone'
    """)


def test_time_repeat_1():
    # Verify that %time autoimport works.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64decode("dGVsZWdyYXBo")
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: 'telegraph'
        In [3]: %time b64decode("ZW1haWw=")
        CPU times: ...
        Wall time: ...
        Out[3]: 'email'
    """)


def test_time_complete_1():
    # Verify that tab completion works with %time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %time b64de\tcode('c2hpcnQ=')
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: 'shirt'
    """)


def test_time_complete_menu_1():
    # Verify that menu tab completion works with %time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: time b64\t
        b64decode  b64encode
        In [2]: time b64\x06d\tecode('cGFudHM=')
        [PYFLYBY] from base64 import b64decode
        CPU times: ...
        Wall time: ...
        Out[2]: 'pants'
    """)


def test_time_complete_autoimport_member_1():
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: time base64.b6\t
        [PYFLYBY] import base64
        In [2]: time base64.b6
        base64.b64decode  base64.b64encode
        In [2]: time base64.b64\x06dec\tode('amFja2V0')
        CPU times: ...
        Wall time: ...
        Out[2]: 'jacket'
    """)


def test_prun_1():
    # Verify that %prun works, autoimports the first time, but not the second
    # time.
    ipython("""
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %prun b64decode("RWluc3RlaW4=")
        [PYFLYBY] from base64 import b64decode
        ... function calls in ... seconds
        ....
        In [3]: b64decode("SGF3a2luZw==")
        Out[3]: 'Hawking'
        In [4]: %prun b64decode("TG9yZW50eg==")
        ... function calls in ... seconds
        ....
    """)


def test_error_during_enable_1():
    # Verify that if an error occurs during enabling, that we disable the
    # autoimporter.  Verify that we don't attempt to re-enable again.
    ipython("""
        In [1]: import pyflyby
        In [2]: pyflyby._interactive.advise = None
        In [3]: pyflyby.enable_auto_importer()
        [PYFLYBY] TypeError: 'NoneType' object is not callable
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        In [4]: print 'hello'
        hello
        In [5]: sys
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'sys' is not defined
        In [6]: pyflyby.enable_auto_importer()
        [PYFLYBY] Not reattempting to enable auto importer after earlier error
    """)
