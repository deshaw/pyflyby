# pyflyby/test_interactive.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import IPython
import atexit
import errno
import fcntl
import os
import pytest
import re
import readline
from   shutil                   import rmtree
import subprocess
import sys
from   tempfile                 import NamedTemporaryFile, mkdtemp
import termios
from   textwrap                 import dedent
import time
import tty

import pyflyby
from   pyflyby._util            import EnvVarCtx, memoize


@memoize
def _extra_pythonpath_dir():
    """
    Return a path to use as an extra PYTHONPATH component.
    """
    if sys.platform != "darwin":
        return None
    # On Darwin, we need a hack to make sure IPython gets GNU readline instead
    # of libedit.
    if "libedit" not in readline.__doc__:
        return None
    dir = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    atexit.register(lambda: rmtree(dir))
    import site
    sitepackages = os.path.join(os.path.dirname(site.__file__), "site-packages")
    readline_fn = os.path.abspath(os.path.join(sitepackages, "readline.so"))
    if not os.path.isfile(readline_fn):
        raise ValueError("Couldn't find readline")
    os.symlink(readline_fn, os.path.join(dir, "readline.so"))
    return dir


def ptypipe(command, stdin="", timeout=300):
    # Create a new pseudo terminal.
    master, slave = os.openpty()
    tty.setraw(master, termios.TCSANOW)
    # Spawn the subprocess.
    proc = subprocess.Popen(
        command,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        close_fds=True,
    )
    # Write the input.  This assumes that the input is small enough to fit in
    # the buffer size; if that ever is no longer True, we'll need to stuff it
    # in the loop after checking select().
    if stdin and not stdin.endswith("\n"):
        stdin += "\n"
    stdin += "exit()\n"
    os.write(master, stdin)
    # We don't need this anymore.
    os.close(slave)
    # Allow ourselves to read without blocking.
    fcntl_flags = fcntl.fcntl(master, fcntl.F_GETFL)
    fcntl.fcntl(master, fcntl.F_SETFL, fcntl_flags | os.O_NONBLOCK)
    # Get output.
    output = []
    start_time = time.time()
    while True:
        # Try to read data.
        try:
            data = os.read(master, 4096)
        except OSError as e:
            if e.errno not in [errno.EWOULDBLOCK, errno.EIO]:
                raise
            data = None
        if data:
            output.append(data)
        elif proc.poll() is not None:
            # Process has finished and no more data.
            break
        else:
            time.sleep(0.01)
            if time.time() > start_time + timeout:
                raise RuntimeError(
                    "Timed out waiting for output from %s; waited %.1fs"
                    % (command[0], time.time() - start_time))
    os.close(master)
    result = "".join(output)
    result = result.replace("\r\n", "\n")
    return result


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


def touch(filename):
    with open(filename, 'a'):
        pass


def ipython(stdin, autocall=False):
    ipython_dir = mkdtemp(
        prefix="pyflyby_test_ipython_", suffix=".tmp")
    try:
        pypath = [os.path.dirname(os.path.dirname(pyflyby.__file__))]
        extra = _extra_pythonpath_dir()
        if extra:
            pypath.append(extra)
        pypath += os.environ["PYTHONPATH"].split(":")
        cmd = [
            "env",
            "PYTHONPATH=%s" % ":".join(pypath),
            "PYTHONSTARTUP=",
        ]
        if '/.tox/' in sys.prefix:
            # Get the ipython from our (tox virtualenv) path.
            cmd += [os.path.join(os.path.dirname(sys.executable), "ipython")]
        else:
            cmd += ["ipython"]
        if _IPYTHON_VERSION >= (0, 11):
            cmd += [
                "--ipython-dir=%s" % (ipython_dir,),
                "--no-confirm-exit",
                "--no-banner",
                "--quiet",
                "--quick",
            ]
            if autocall:
                cmd += ["--autocall=1"]
        elif _IPYTHON_VERSION >= (0, 10):
            cmd += [
                "-ipythondir=%s" % (ipython_dir,),
                "-noconfirm_exit",
                "-nomessages",
                "-nobanner",
                "-quick",
            ]
            if autocall:
                cmd += ["-autocall=1"]
            touch(os.path.join(ipython_dir, "ipythonrc"))
            touch(os.path.join(ipython_dir, "ipy_user_conf.py"))
        else:
            raise NotImplementedError("Don't know how to test IPython version %s"
                                      % (_IPYTHON_VERSION,))
        result = ptypipe(cmd, stdin=stdin)
    finally:
        rmtree(ipython_dir)
    # Remove ANSI escape sequences.
    result = remove_ansi_escapes(result)
    # Remove banners.
    result = re.sub(re.compile("^Launching IPython in quick mode. No config file read.\n", re.M), "", result)
    # Remove input prompts.  We don't include the input string anyway.
    result = re.sub(re.compile(r"\n?^In \[[0-9]+\]: ?", re.M), "", result)
    # Make traceback output stable.
    result = re.sub(re.compile(r"(^/.*?/)?<(ipython-input-[0-9]+-[0-9a-f]+|ipython console)>", re.M), "<ipython-input>", result)
    result = re.sub(re.compile(r"^----> .*\n", re.M), "", result)
    # Compress newlines.
    result = re.sub("\n\n+", "\n", result)
    return result


def test_ipython_1():
    # Test that we can run ipython and get results back.
    input = "print 6*7"
    result = ipython(input).strip()
    assert result == "42"


def test_pyflyby_file_1():
    # Check that our test setup is getting the right pyflyby.
    input = "import pyflyby; print pyflyby.__file__\n"
    result = ipython(input).strip().replace(".pyc", ".py")
    expected = pyflyby.__file__.replace(".pyc", ".py")
    assert result == expected


def test_pyflyby_version_1():
    # Check that our test setup is getting the right pyflyby.
    input = "import pyflyby; print pyflyby.__version__\n"
    result = ipython(input).strip()
    expected = pyflyby.__version__
    assert result == expected


def test_ipython_file_1():
    # Check that our test setup is getting the right IPython.
    input = "import IPython; print IPython.__file__\n"
    result = ipython(input).strip()
    expected = IPython.__file__
    assert result == expected


def test_ipython_version_1():
    # Check that our test setup is getting the right IPython.
    input = "import IPython; print IPython.__version__\n"
    result = ipython(input).strip()
    expected = IPython.__version__
    assert result == expected


def test_autoimport_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        '@'+b64decode('SGVsbG8=')+'@'
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Out[2]: '@Hello@'
    """).lstrip()
    assert result == expected


def test_no_autoimport_1():
    # Test that without pyflyby installed, we do get NameError.  This is
    # really a test that our testing infrastructure is OK and not accidentally
    # picking up pyflyby configuration installed in a system or user config.
    input = dedent("""
        '@'+b64decode('SGVsbG8=')+'@'
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'b64decode' is not defined
    """).lstrip()
    assert result == expected


def test_autoimport_statement_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        print b64decode('SGVsbG8=')
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Hello
    """).lstrip()
    assert result == expected


def test_autoimport_pyflyby_path_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        list(product('ab','cd'))
        groupby
    """).lstrip()
    with NamedTemporaryFile() as f:
        f.write("from itertools import product\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from itertools import product
        Out[2]: [('a', 'c'), ('a', 'd'), ('b', 'c'), ('b', 'd')]
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'groupby' is not defined
    """).lstrip()
    assert result == expected


# Skip tab completion tests in IPython 0.10 and earlier.  For IPython 0.10,
# tab completion does work, but somehow "\t" via pty doesn't trigger tab
# completion.  It's unclear why, but it's not important to make the test case
# work for this old version of IPython, so we just skip it.
skip_if_ipython_010 = pytest.mark.skipif(
    _IPYTHON_VERSION < (0, 11),
    reason="test only works for IPython >= 0.11")


@skip_if_ipython_010
def test_complete_symbol_basic_1():
    # Check that tab completion works.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        b64deco\t('eHl6enk=')
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'xyzzy'
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_import_check_1():
    # Check importing into the namespace.  If we use b64decode from base64,
    # then b64decode should be imported into the namespace, but base64 should
    # not.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        'base64' in globals()
        'b64decode' in globals()
        b64deco\t('UnViaWNvbg==')
        'base64' in globals()
        'b64decode' in globals()
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        Out[2]: False
        Out[3]: False
        [PYFLYBY] from base64 import b64decode
        Out[4]: 'Rubicon'
        Out[5]: False
        Out[6]: True
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_instance_identity_1():
    # Check that automatic symbols give the same instance (i.e., no proxy
    # objects involved).
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        f = b64deco\t
        f is __import__('base64').b64decode
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Out[3]: True
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_member_1():
    # Check that tab completion in members works.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        base64.b64d\t('bW9udHk=')
    """).lstrip()
    result = ipython(input)
    # We expect "base64.b64d" to be reprinted again after the [PYFLYBY] log
    # line.  (This differs from the "b64deco\t" case: in that case, nothing
    # needs to be imported to satisfy the tab completion, and therefore no log
    # line was printed.  OTOH, for an input of "base64.b64deco\t", we need to
    # first do an automatic "import base64", which causes log output during
    # the prompt, which means reprinting the input so far.)
    expected = dedent("""
        [PYFLYBY] import base64
        base64.b64dOut[2]: 'monty'
    """)
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_import_module_as_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        b64.b64d\t('cm9zZWJ1ZA==')
    """).lstrip()
    with NamedTemporaryFile() as f:
        f.write("import base64 as b64\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            result = ipython(input)
    expected = dedent("""
        [PYFLYBY] import base64 as b64
        b64.b64dOut[2]: 'rosebud'
    """)
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_statement_1():
    # Check that tab completion in statements works.  This requires a more
    # sophisticated code path than test_complete_symbol_basic_1.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        if 1: print b64deco\t('SHVudGVy')
    """).lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Hunter
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
@pytest.mark.xfail(
    _IPYTHON_VERSION < (0, 12),
    reason="autocall completion doesn't work on IPython < 0.12")
def test_complete_symbol_autocall_1():
    # Check that tab completion works with autocall.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        str.upper b64deco\t('Q2hld2JhY2Nh')
    """).lstrip()
    result = ipython(input, autocall=True)
    expected = dedent("""
        ------> str.upper(b64decode('Q2hld2JhY2Nh'))
        [PYFLYBY] from base64 import b64decode
        Out[2]: 'CHEWBACCA'
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_any_module_1():
    # Check that completion and autoimport works for an arbitrary module in
    # $PYTHONPATH.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        m18908697_\t.f_68421204()
    """).lstrip()
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m18908697_foo.py"%d, 'w') as f:
            f.write(dedent("""
                def f_68421204(): return 'good'
            """))
        with EnvVarCtx(PYTHONPATH=d):
            result = ipython(input)
    finally:
        rmtree(d)
    expected = dedent("""
        [PYFLYBY] import m18908697_foo
        Out[2]: 'good'
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_any_module_member_1():
    # Check that completion on members works for an arbitrary module in
    # $PYTHONPATH.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        m51145108_\t.f_76313558_\t()
    """).lstrip()
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m51145108_foo.py"%d, 'w') as f:
            f.write(dedent("""
                def f_76313558_59577191(): return 'ok'
            """))
        with EnvVarCtx(PYTHONPATH=d):
            result = ipython(input)
    finally:
        rmtree(d)
    expected = dedent("""
        [PYFLYBY] import m51145108_foo
        m51145108_foo.f_76313558_Out[2]: 'ok'
    """)
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_bad_1():
    # Check that if we have a bad item in known imports, we complete it still.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        foo_31221052_\t
    """).lstrip()
    with NamedTemporaryFile() as f:
        f.write("import foo_31221052_bar\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            result = ipython(input)
    expected = dedent("""
        [PYFLYBY] import foo_31221052_bar
        [PYFLYBY] Error attempting to 'import foo_31221052_bar': ImportError: No module named foo_31221052_bar
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'foo_31221052_bar' is not defined
    """).lstrip()
    assert result == expected


@skip_if_ipython_010
def test_complete_symbol_bad_as_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        bar_98073069_\t.asdf
    """).lstrip()
    with NamedTemporaryFile() as f:
        f.write("import foo_86487172 as bar_98073069_quux\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            result = ipython(input)
    expected = dedent("""
        [PYFLYBY] import foo_86487172 as bar_98073069_quux
        [PYFLYBY] Error attempting to 'import foo_86487172 as bar_98073069_quux': ImportError: No module named foo_86487172
        ---------------------------------------------------------------------------
        NameError                                 Traceback (most recent call last)
        <ipython-input> in <module>()
        NameError: name 'bar_98073069_quux' is not defined
    """).lstrip()
    assert result == expected


def test_pinfo_1():
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        f34229186?
    """)
    d = mkdtemp(prefix="pyflyby_", suffix=".tmp")
    try:
        with open("%s/m17426814.py"%d, 'w') as f:
            f.write(dedent("""
                def f34229186():
                    'hello from 34229186'
            """).lstrip())
        with NamedTemporaryFile() as pf:
            pf.write("from m17426814 import f34229186\n")
            pf.flush()
            with EnvVarCtx(PYTHONPATH=d, PYFLYBY_PATH=pf.name):
                result = ipython(input)
    finally:
        rmtree(d)
    assert "[PYFLYBY] from m17426814 import f34229186" in result
    assert "hello from 34229186" in result
