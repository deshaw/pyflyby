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
    if "GNU readline" in readline.__doc__:
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



@memoize
def _ipython_version():
    return _parse_version(IPython.__version__)


def touch(filename):
    with open(filename, 'a'):
        pass


def ipython(stdin):
    ipython_dir = mkdtemp(
        prefix="pyflyby_test_ipython_", suffix=".tmp")
    try:
        version = _ipython_version()
        pypath = [os.path.dirname(os.path.dirname(pyflyby.__file__))]
        extra = _extra_pythonpath_dir()
        if extra:
            pypath.append(extra)
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
        if version >= (0, 11):
            cmd += [
                "--ipython-dir=%s" % (ipython_dir,),
                "--no-confirm-exit",
                "--no-banner",
                "--quiet",
                "--quick",
            ]
        elif version >= (0, 10):
            cmd += [
                "-ipythondir=%s" % (ipython_dir,),
                "-noconfirm_exit",
                "-nomessages",
                "-nobanner",
                "-quick",
            ]
            touch(os.path.join(ipython_dir, "ipythonrc"))
            touch(os.path.join(ipython_dir, "ipy_user_conf.py"))
        else:
            raise NotImplementedError("Don't know how to test IPython version %s"
                                      % (version,))
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
    # # Ignore a readline-vs-libedit warnings.
    # result = re.sub(re.compile("^/.*?rlineimpl.py:[0-9]+: RuntimeWarning: ?\n[*][*][*][*]+\nlibedit detected - (.|\n)+\n[*][*][*][*]+\n( *RuntimeWarning\)\n)?", re.M), "", result)
    # result = re.sub(re.compile("^.* libedit detected.\n", re.M), "", result)
    # result = re.sub(re.compile(r"^/.*?rlineimpl.py:[0-9]+: RuntimeWarning: .*?libedit detected.*?\n( *RuntimeWarning\)\n)?", re.M), "", result)
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


# For IPython 0.10, tab completion does work, but somehow "\t" via pty doesn't
# trigger tab completion.  It's unclear why, but it's not important to make
# the test case work for this old version of IPython, so we just skip it.
@pytest.mark.skipif(_ipython_version() < (0, 11),
                    reason="test only works for IPython >= 0.11")
def test_complete_symbol_1():
    # Check that tab completion works.
    input = dedent("""
        import pyflyby; pyflyby.install_auto_importer()
        print b64deco\t('SHVudGVy')\n""").lstrip()
    result = ipython(input)
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        Hunter
    """).lstrip()
    assert result == expected
