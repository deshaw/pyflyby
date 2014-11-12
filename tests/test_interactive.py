# pyflyby/test_interactive.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import IPython
import atexit
from   cStringIO                import StringIO
import difflib
import os
import pexpect
import pytest
import random
import re
import readline
from   shutil                   import rmtree
import signal
import sys
from   tempfile                 import NamedTemporaryFile, mkdtemp
from   textwrap                 import dedent

import pyflyby
from   pyflyby._util            import EnvVarCtx, memoize


# TODO: create a doctest-like wrapper that extracts inputs from the expected
# output template.

# TODO: test IPython kernel (closest thing to testing Notebook)

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
    regexp = re.compile(regexp)
    if not regexp.match(result):
        msg = []
        msg.append("Expected:")
        msg.extend("     %s"%line for line in expected.splitlines())
        msg.append("Result:")
        msg.extend("     %s"%line for line in result.splitlines())
        msg.append("Diff:")
        msg.extend("   %s"%line for line in difflib.ndiff(expected.splitlines(), result.splitlines()))
        msg = "\n".join(msg)
        pytest.fail(msg)


def test_selftest_1():
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


def test_selftest_2():
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
    import _pytest
    with pytest.raises(_pytest.runner.Failed):
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
_IPYTHON_PROMPT2 = "\n   [.][.][.]: "
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
    if isinstance(PYTHONPATH, basestring):
        PYTHONPATH = [PYTHONPATH]
    pypath += PYTHONPATH
    pypath += os.environ["PYTHONPATH"].split(":")
    return ":".join(pypath)


def _build_ipython_cmd(ipython_dir, autocall=False):
    """
    Prepare the command to run IPython.
    """
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
        with open(os.path.join(ipython_dir, "ipythonrc"), 'w') as f:
            f.write(dedent("""
                readline_parse_and_bind tab: complete
                readline_parse_and_bind set show-all-if-ambiguous on
            """))
        with open(os.path.join(ipython_dir, "ipy_user_conf.py"), 'w'):
            pass
    else:
        raise NotImplementedError("Don't know how to test IPython version %s"
                                  % (_IPYTHON_VERSION,))
    return cmd


PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
PYFLYBY_PATH = os.path.join(PYFLYBY_HOME, "etc/pyflyby")


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


def ipython(input, autocall=False, PYTHONPATH=[], PYFLYBY_PATH=PYFLYBY_PATH):
    # Create a temporary directory which we'll use as our IPYTHONDIR.
    ipython_dir = mkdtemp(prefix="pyflyby_test_ipython_", suffix=".tmp")
    child = None
    try:
        # Prepare environment variables.
        env = {}
        env["PYFLYBY_PATH"]  = PYFLYBY_PATH
        env["PYTHONPATH"]    = _build_pythonpath(PYTHONPATH)
        env["PYTHONSTARTUP"] = ""
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
    input = "print 6*7\n6*9"
    result = ipython(input)
    expected = """
        In [1]: print 6*7
        42
        In [2]: 6*9
        Out[2]: 54
    """
    assert_match(result, expected)


def test_pyflyby_file_1():
    # Check that our test setup is getting the right pyflyby.
    input = """
        import pyflyby
        print '<''<<%s>>>' % (pyflyby.__file__.replace(".pyc", ".py"),)
    """
    output = ipython(input)
    result = re.search("<<<(.*?)>>>", output).group(1)
    expected = pyflyby.__file__.replace(".pyc", ".py")
    assert result == expected


def test_pyflyby_version_1():
    # Check that our test setup is getting the right pyflyby.
    input = """
        import pyflyby
        print '<''<<%s>>>' % (pyflyby.__version__,)
    """
    output = ipython(input)
    result = re.search("<<<(.*?)>>>", output).group(1)
    expected = pyflyby.__version__
    assert result == expected


def test_ipython_file_1():
    # Check that our test setup is getting the right IPython.
    input = """
        import IPython
        print '<''<<%s>>>' % (IPython.__file__,)
    """
    output = ipython(input)
    result = re.search("<<<(.*?)>>>", output).group(1)
    expected = IPython.__file__
    assert result == expected


def test_ipython_version_1():
    # Check that our test setup is getting the right IPython.
    input = """
        import IPython
        print '<''<<%s>>>' % (IPython.__version__,)
    """
    output = ipython(input)
    result = re.search("<<<(.*?)>>>", output).group(1)
    expected = IPython.__version__
    assert result == expected


def test_autoimport_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        '@'+b64decode('SGVsbG8=')+'@'
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: '@'+b64decode('SGVsbG8=')+'@'
        [PYFLYBY] from base64 import b64decode
        Out[2]: '@Hello@'
    """
    assert_match(result, expected)


def test_no_autoimport_1():
    # Test that without pyflyby installed, we do get NameError.  This is
    # really a test that our testing infrastructure is OK and not accidentally
    # picking up pyflyby configuration installed in a system or user config.
    input = """
        '@'+b64decode('SGVsbG8=')+'@'
    """
    result = ipython(input)
    expected = """
        In [1]: '@'+b64decode('SGVsbG8=')+'@'
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64decode' is not defined
    """
    assert_match(result, expected)


def test_autoimport_symbol_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        b64decode
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode
        [PYFLYBY] from base64 import b64decode
        Out[2]: <function ...b64decode...>
    """
    assert_match(result, expected)


def test_autoimport_statement_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print b64decode('SGVsbG8=')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('SGVsbG8=')
        [PYFLYBY] from base64 import b64decode
        Hello
    """
    assert_match(result, expected)


def test_autoimport_multiple_imports_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print b64encode("koala"), b64decode("a2FuZ2Fyb28=")
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64encode("koala"), b64decode("a2FuZ2Fyb28=")
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] from base64 import b64encode
        a29hbGE= kangaroo
    """
    assert_match(result, expected)


def test_autoimport_multiline_statement_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        if 1:
            print b64decode('dHVydGxl')

        print b64decode('bGFtYQ==')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print b64decode('dHVydGxl')
           ...:
        [PYFLYBY] from base64 import b64decode
        turtle
        In [3]: print b64decode('bGFtYQ==')
        lama
    """
    assert_match(result, expected)


def test_autoimport_multiline_continued_statement_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        if 1:
            (sys.
                stdout
                    .write(
                        b64decode(
                            'bWljcm9waG9uZQ==')))

        print b64decode('bG91ZHNwZWFrZXI=')
    """
    result = ipython(input)
    expected = """
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
    """
    assert_match(result, expected)


def test_autoimport_multiline_continued_statement_fake_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        if 1:
            print (unknown_symbol_37320899.
                b64encode
                )

        if 1:
            print b64encode('y')

        print b64decode('YmFzZWJhbGw=')
    """
    result = ipython(input)
    expected = """
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
    """
    assert_match(result, expected)


def test_autoimport_pyflyby_path_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        list(product('ab','cd'))
        groupby
    """
    with NamedTemporaryFile() as f:
        f.write("from itertools import product\n")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: list(product('ab','cd'))
        [PYFLYBY] from itertools import product
        Out[2]: [('a', 'c'), ('a', 'd'), ('b', 'c'), ('b', 'd')]
        In [3]: groupby
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'groupby' is not defined
    """
    assert_match(result, expected)


def test_autoimport_autocall_arg_1():
    # Check that we can autoimport the argument of an autocall.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        str.upper b64decode('a2V5Ym9hcmQ=')
    """
    result = ipython(input, autocall=True)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: str.upper b64decode('a2V5Ym9hcmQ=')
        ------> str.upper(b64decode('a2V5Ym9hcmQ='))
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'KEYBOARD'
    """
    assert_match(result, expected)


def test_autoimport_autocall_function_1():
    # Check that we can autoimport the function to autocall.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        b64decode 'bW91c2U='
    """
    result = ipython(input, autocall=True)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode 'bW91c2U='
        [PYFLYBY] from base64 import b64decode
        ------> b64decode('bW91c2U=')
        Out[2]: 'mouse'
    """
    assert_match(result, expected)


def test_complete_symbol_basic_1():
    # Check that tab completion works.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        b64deco\t('eHl6enk=')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64decode('eHl6enk=')
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'xyzzy'
    """
    assert_match(result, expected)


def test_complete_symbol_multiple_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print b64\td\t
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64
        b64decode  b64encode
        In [2]: print b64decode
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """
    assert_match(result, expected)


def test_complete_symbol_partial_multiple_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print b6\td\t
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b6
        b64decode  b64encode
        In [2]: print b64decode
        [PYFLYBY] from base64 import b64decode
        <function b64decode...>
    """
    assert_match(result, expected)


def test_complete_symbol_import_check_1():
    # Check importing into the namespace.  If we use b64decode from base64,
    # then b64decode should be imported into the namespace, but base64 should
    # not.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        'base64' in globals()
        'b64decode' in globals()
        b64deco\t('UnViaWNvbg==')
        'base64' in globals()
        'b64decode' in globals()
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 'base64' in globals()
        Out[2]: False
        In [3]: 'b64decode' in globals()
        Out[3]: False
        In [4]: b64decode('UnViaWNvbg==')
        [PYFLYBY] from base64 import b64decode
        Out[4]: 'Rubicon'
        In [5]: 'base64' in globals()
        Out[5]: False
        In [6]: 'b64decode' in globals()
        Out[6]: True
    """
    assert_match(result, expected)


def test_complete_symbol_instance_identity_1():
    # Check that automatic symbols give the same instance (i.e., no proxy
    # objects involved).
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        f = b64deco\t
        f is __import__('base64').b64decode
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: f = b64decode
        [PYFLYBY] from base64 import b64decode
        In [3]: f is __import__('base64').b64decode
        Out[3]: True
    """
    assert_match(result, expected)


def test_complete_symbol_member_1():
    # Check that tab completion in members works.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        base64.b64d\t('bW9udHk=')
    """
    result = ipython(input)
    # We expect "base64.b64d" to be reprinted again after the [PYFLYBY] log
    # line.  (This differs from the "b64deco\t" case: in that case, nothing
    # needs to be imported to satisfy the tab completion, and therefore no log
    # line was printed.  OTOH, for an input of "base64.b64deco\t", we need to
    # first do an automatic "import base64", which causes log output during
    # the prompt, which means reprinting the input so far.)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: base64.b64d
        [PYFLYBY] import base64
        In [2]: base64.b64decode('bW9udHk=')
        Out[2]: 'monty'
    """
    assert_match(result, expected)


def test_complete_symbol_member_multiple_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print base64.b64\t
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print base64.b64
        [PYFLYBY] import base64
        In [2]: print base64.b64
        base64.b64decode  base64.b64encode
        In [2]: print base64.b64
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        <ipython-input> in <module>()
        AttributeError: 'module' object has no attribute 'b64'
    """
    assert_match(result, expected)


def test_complete_symbol_member_partial_multiple_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        print base64.b6\t
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print base64.b6
        [PYFLYBY] import base64
        In [2]: print base64.b6
        base64.b64decode  base64.b64encode
        In [2]: print base64.b64
        ---------------------------------------------------------------------------
        AttributeError                            Traceback (most recent call last)
        <ipython-input> in <module>()
        AttributeError: 'module' object has no attribute 'b64'
    """
    assert_match(result, expected)


def test_complete_symbol_import_module_as_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        b64.b64d\t('cm9zZWJ1ZA==')
    """
    with NamedTemporaryFile() as f:
        f.write("import base64 as b64\n")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: b64.b64d
        [PYFLYBY] import base64 as b64
        In [2]: b64.b64decode('cm9zZWJ1ZA==')
        Out[2]: 'rosebud'
    """
    assert_match(result, expected)


def test_complete_symbol_statement_1():
    # Check that tab completion in statements works.  This requires a more
    # sophisticated code path than test_complete_symbol_basic_1.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        x = b64deco\t('SHVudGVy')
        print x
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: x = b64decode('SHVudGVy')
        [PYFLYBY] from base64 import b64decode
        In [3]: print x
        Hunter
    """
    assert_match(result, expected)


def test_complete_symbol_multiline_statement_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        if 1:
            print b64deco\t('emVicmE=')
            print 42

        print b64d\t('dGlnZXI=')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print b64decode('emVicmE=')
           ...:     print 42
           ...:
        [PYFLYBY] from base64 import b64decode
        zebra
        42
        In [3]: print b64decode('dGlnZXI=')
        tiger
    """
    assert_match(result, expected)


def test_complete_symbol_multiline_statement_member_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        if 1:
            print base64.b64d\t('Z2lyYWZmZQ==')
            print 42

        print b64d\t('bGlvbg==')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: if 1:
           ...:     print base64.b64d
        [PYFLYBY] import base64
           ...:     print base64.b64decode('Z2lyYWZmZQ==')
           ...:     print 42
           ...:
        giraffe
        42
        In [3]: print b64decode('bGlvbg==')
        [PYFLYBY] from base64 import b64decode
        lion
    """
    assert_match(result, expected)


def test_complete_symbol_autocall_arg_1():
    # Check that tab completion works with autocall.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        str.upper b64deco\t('Q2hld2JhY2Nh')
    """
    result = ipython(input, autocall=True)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: str.upper b64decode('Q2hld2JhY2Nh')
        ------> str.upper(b64decode('Q2hld2JhY2Nh'))
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'CHEWBACCA'
    """
    assert_match(result, expected)


def test_complete_symbol_any_module_1():
    # Check that completion and autoimport works for an arbitrary module in
    # $PYTHONPATH.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        m18908697_\t.f_68421204()
    """
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m18908697_foo.py"%d, 'w') as f:
            f.write(dedent("""
                def f_68421204(): return 'good'
            """))
        result = ipython(input, PYTHONPATH=d)
    finally:
        rmtree(d)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: m18908697_foo.f_68421204()
        [PYFLYBY] import m18908697_foo
        Out[2]: 'good'
    """
    assert_match(result, expected)


def test_complete_symbol_any_module_member_1():
    # Check that completion on members works for an arbitrary module in
    # $PYTHONPATH.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        m51145108_\t.f_76313558_\t()
    """
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m51145108_foo.py"%d, 'w') as f:
            f.write(dedent("""
                def f_76313558_59577191(): return 'ok'
            """))
        result = ipython(input, PYTHONPATH=d)
    finally:
        rmtree(d)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: m51145108_foo.f_76313558_
        [PYFLYBY] import m51145108_foo
        In [2]: m51145108_foo.f_76313558_59577191()
        Out[2]: 'ok'
    """
    assert_match(result, expected)


def test_complete_symbol_bad_1():
    # Check that if we have a bad item in known imports, we complete it still.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        foo_31221052_\t
    """
    with NamedTemporaryFile() as f:
        f.write("import foo_31221052_bar\n")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: foo_31221052_bar
        [PYFLYBY] import foo_31221052_bar
        [PYFLYBY] Error attempting to 'import foo_31221052_bar': ImportError: No module named foo_31221052_bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'foo_31221052_bar' is not defined
    """
    assert_match(result, expected)


def test_complete_symbol_bad_as_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        bar_98073069_\t.asdf
    """
    with NamedTemporaryFile() as f:
        f.write("import foo_86487172 as bar_98073069_quux\n")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: bar_98073069_quux.asdf
        [PYFLYBY] import foo_86487172 as bar_98073069_quux
        [PYFLYBY] Error attempting to 'import foo_86487172 as bar_98073069_quux': ImportError: No module named foo_86487172
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar_98073069_quux' is not defined
    """
    assert_match(result, expected)


def test_disable_reenable_autoimport_1():
    input = """
        import pyflyby
        pyflyby.enable_auto_importer()
        b64encode('blue')
        pyflyby.disable_auto_importer()
        b64decode('cmVk')        # expect NameError since no auto importer
        b64encode('green')       # should still work because already imported
        pyflyby.enable_auto_importer()
        b64decode('eWVsbG93')    # should work now
    """
    result = ipython(input)
    expected = """
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
    """
    assert_match(result, expected)


def test_disable_reenable_completion_1():
    input = """
        import pyflyby
        pyflyby.enable_auto_importer()
        b64enco\t('flower')
        pyflyby.disable_auto_importer()
        b64deco\t('Y2xvdWQ=')   # expect NameError since no auto importer
        b64enco\t('tree')       # should still work because already imported
        pyflyby.enable_auto_importer()
        b64deco\t('Y2xvdWQ=')   # should work now
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: b64encode('flower')
        [PYFLYBY] from base64 import b64encode
        Out[3]: 'Zmxvd2Vy'
        In [4]: pyflyby.disable_auto_importer()
        In [5]: b64deco('Y2xvdWQ=')   # expect NameError since no auto importer
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64deco' is not defined
        In [6]: b64encode('tree')       # should still work because already imported
        Out[6]: 'dHJlZQ=='
        In [7]: pyflyby.enable_auto_importer()
        In [8]: b64decode('Y2xvdWQ=')   # should work now
        [PYFLYBY] from base64 import b64decode
        Out[8]: 'cloud'
    """
    assert_match(result, expected)


def test_pinfo_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        f34229186?
    """
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m17426814.py"%d, 'w') as f:
            f.write(dedent("""
                def f34229186():
                    'hello from '  '34229186'
            """))
        with NamedTemporaryFile() as pf:
            pf.write("from m17426814 import f34229186\n")
            pf.flush()
            result = ipython(input, PYTHONPATH=d, PYFLYBY_PATH=pf.name)
    finally:
        rmtree(d)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: f34229186?
        [PYFLYBY] from m17426814 import f34229186
        ....
        Docstring:....hello from 34229186
    """
    assert_match(result, expected)


def test_error_during_auto_import_symbol_1():
    input = """
        import pyflyby
        pyflyby.enable_auto_importer()
        6*7
        unknown_symbol_68470042
        unknown_symbol_76663387
    """
    with NamedTemporaryFile() as f:
        f.write("3+")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
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
    """
    assert_match(result, expected)


def test_error_during_auto_import_expression_1():
    input = """
        import pyflyby
        pyflyby.enable_auto_importer()
        6*7
        42+unknown_symbol_72161870
        42+unknown_symbol_48517397
    """
    with NamedTemporaryFile() as f:
        f.write("3+")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
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
    """
    assert_match(result, expected)


def test_error_during_completion_1():
    input = """
        import pyflyby
        pyflyby.enable_auto_importer()
        100
        unknown_symbol_14954304_\tfoo
        200
        unknown_symbol_69697066_\tfoo
        300
    """
    with NamedTemporaryFile() as f:
        f.write("3+")
        f.flush()
        result = ipython(input, PYFLYBY_PATH=f.name)
    expected = """
        In [1]: import pyflyby
        In [2]: pyflyby.enable_auto_importer()
        In [3]: 100
        Out[3]: 100
        In [4]: unknown_symbol_14954304_
        [PYFLYBY] SyntaxError: While parsing ...: invalid syntax (..., line 1)
        [PYFLYBY] Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.
        [PYFLYBY] Disabling pyflyby auto importer.
        In [4]: unknown_symbol_14954304_foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_14954304_foo' is not defined
        In [5]: 200
        Out[5]: 200
        In [6]: unknown_symbol_69697066_foo
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'unknown_symbol_69697066_foo' is not defined
        In [7]: 300
        Out[7]: 300
    """
    assert_match(result, expected)


def test_syntax_error_in_user_code_1():
    # Check that we don't inadvertently disable the autoimporter due to
    # a syntax error in the interactive command.
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        1/
        b64decod\t("bWlkbmlnaHQ=")
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: 1/
        ....
        SyntaxError: invalid syntax
        In [3]: b64decode("bWlkbmlnaHQ=")
        [PYFLYBY] from base64 import b64decode
        Out[3]: 'midnight'
    """
    assert_match(result, expected)


def test_run_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print 'hello'
            print b64decode('RXVjbGlk')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64decode
        hello
        Euclid
    """
    assert_match(result, expected)


def test_run_repeat_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('Q2FudG9y')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run {f.name}
            run {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64decode
        Cantor
        In [3]: run ...
        [PYFLYBY] from base64 import b64decode
        Cantor
    """
    assert_match(result, expected)


def test_run_separate_script_namespace_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('UmllbWFubg==')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            print b64decode('Rmlib25hY2Np')
            run {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('Rmlib25hY2Np')
        [PYFLYBY] from base64 import b64decode
        Fibonacci
        In [3]: run ...
        [PYFLYBY] from base64 import b64decode
        Riemann
    """
    assert_match(result, expected)


def test_run_separate_script_namespace_2():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('SGlsYmVydA==')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            def b64decode(x):
                return "booger"

            b64decode('x')
            run {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def b64decode(x):
           ...:     return "booger"
           ...:
        In [3]: b64decode('x')
        Out[3]: 'booger'
        In [4]: run ...
        [PYFLYBY] from base64 import b64decode
        Hilbert
    """
    assert_match(result, expected)


def test_run_modify_interactive_namespace_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            x = b64decode('RmVybWF0')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run {f.name}
            x
            b64decode('TGFwbGFjZQ==')
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64decode
        In [3]: x
        Out[3]: 'Fermat'
        In [4]: b64decode('TGFwbGFjZQ==')
        Out[4]: 'Laplace'
    """
    assert_match(result, expected)


def test_run_i_auto_import_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('RGVzY2FydGVz')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run -i {f.name}
            print b64decode('R2F1c3M=')
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64decode
        Descartes
        In [3]: print b64decode('R2F1c3M=')
        Gauss
    """
    assert_match(result, expected)


def test_run_i_already_imported_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode(k)
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            print b64decode('R3JvdGhlbmRpZWNr')
            k = 'QXJjaGltZWRlcw=='
            run -i {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: print b64decode('R3JvdGhlbmRpZWNr')
        [PYFLYBY] from base64 import b64decode
        Grothendieck
        In [3]: k = 'QXJjaGltZWRlcw=='
        In [4]: run ...
        Archimedes
    """
    assert_match(result, expected)


def test_run_i_repeated_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('S29sbW9nb3Jvdg==')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run -i {f.name}
            run -i {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64decode
        Kolmogorov
        In [3]: run ...
        Kolmogorov
    """
    assert_match(result, expected)


def test_run_i_locally_defined_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64decode('zzz')
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            def b64decode(x):
                return "Bernoulli"

            run -i {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: def b64decode(x):
           ...:     return "Bernoulli"
           ...:
        In [3]: run ...
        Bernoulli
    """
    assert_match(result, expected)


def test_run_syntax_error_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print 'hello'
            print b64decode('UHl0aGFnb3Jhcw==')
            1 /
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run {f.name}
            print b64decode('Q29ud2F5')
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        ....
        SyntaxError: invalid syntax....
        In [3]: print b64decode('Q29ud2F5')
        [PYFLYBY] from base64 import b64decode
        Conway
    """
    assert_match(result, expected)


def test_run_name_main_1():
    with NamedTemporaryFile() as f:
        f.write(dedent("""
            print b64encode(__name__)
        """))
        f.flush()
        input = """
            import pyflyby; pyflyby.enable_auto_importer()
            run {f.name}
        """.format(f=f)
        result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64encode
        X19tYWluX18=
    """
    assert_match(result, expected)


def test_run_name_not_main_1():
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/f81564382.py"%d, 'w') as f:
            f.write(dedent("""
                print b64encode(__name__)
            """))
            f.flush()
            input = """
                import pyflyby; pyflyby.enable_auto_importer()
                run -n {f.name}
            """.format(f=f)
            result = ipython(input)
    finally:
        rmtree(d)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: run ...
        [PYFLYBY] from base64 import b64encode
        ZjgxNTY0Mzgy
    """
    assert_match(result, expected)


def test_timeit_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        %timeit -n 1 -r 1 b64decode('TWljaGVsYW5nZWxv')
        %timeit -n 1 -r 1 b64decode('RGF2aWQ=')
    """
    result = ipython(input)
    expected = """
        In [1]: import pyflyby; pyflyby.enable_auto_importer()
        In [2]: %timeit -n 1 -r 1 b64decode('TWljaGVsYW5nZWxv')
        [PYFLYBY] from base64 import b64decode
        1 loops, best of 1: ... per loop
        In [3]: %timeit -n 1 -r 1 b64decode('RGF2aWQ=')
        1 loops, best of 1: ... per loop
    """
    assert_match(result, expected)


def test_prun_1():
    input = """
        import pyflyby; pyflyby.enable_auto_importer()
        %prun b64decode("RWluc3RlaW4=")
        b64decode("SGF3a2luZw==")
        %prun b64decode("TG9yZW50eg==")
    """
    result = ipython(input)
    expected = """
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
    """
    assert_match(result, expected)


def test_error_during_enable_1():
    input = """
        import pyflyby
        pyflyby._interactive.advise = None
        pyflyby.enable_auto_importer()
        print 'hello'
        sys
        pyflyby.enable_auto_importer()
    """
    result = ipython(input)
    expected = """
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
    """
    assert_match(result, expected)
