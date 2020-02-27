# pyflyby/test_cmdline.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import (absolute_import, division, print_function,
                        with_statement)

from   io                       import BytesIO
import os
import pexpect
import subprocess
import tempfile
from   textwrap                 import dedent

from   six                      import PY2, PY3

from   pyflyby._util            import EnvVarCtx

PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")


def pipe(command, stdin=""):
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    ).communicate(stdin.encode('utf-8'))[0].decode('utf-8').strip()


def test_tidy_imports_stdin_1():
    result = pipe([BIN_DIR+"/tidy-imports"], stdin="os, sys")
    expected = dedent('''
        [PYFLYBY] /dev/stdin: added 'import os'
        [PYFLYBY] /dev/stdin: added 'import sys'
        [PYFLYBY] /dev/stdin: added mandatory 'from __future__ import absolute_import'
        [PYFLYBY] /dev/stdin: added mandatory 'from __future__ import division'
        from __future__ import absolute_import, division

        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


def test_tidy_imports_quiet_1():
    result = pipe([BIN_DIR+"/tidy-imports", "--quiet"], stdin="os, sys")
    expected = dedent('''
        from __future__ import absolute_import, division

        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


def test_tidy_imports_log_level_1():
    with EnvVarCtx(PYFLYBY_LOG_LEVEL="WARNING"):
        result = pipe([BIN_DIR+"/tidy-imports"], stdin="os, sys")
        expected = dedent('''
            from __future__ import absolute_import, division

            import os
            import sys

            os, sys
        ''').strip()
        assert result == expected


def test_tidy_imports_filename_action_print_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(dedent('''
            # hello
            def foo():
                foo() + os + sys
        ''').lstrip())
        f.flush()
        result = pipe([BIN_DIR+"/tidy-imports", f.name])
        expected = dedent('''
            [PYFLYBY] {f.name}: added 'import os'
            [PYFLYBY] {f.name}: added 'import sys'
            [PYFLYBY] {f.name}: added mandatory 'from __future__ import absolute_import'
            [PYFLYBY] {f.name}: added mandatory 'from __future__ import division'
            # hello
            from __future__ import absolute_import, division

            import os
            import sys

            def foo():
                foo() + os + sys
        ''').strip().format(f=f)
        assert result == expected


def test_tidy_imports_filename_action_replace_1():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False, mode='w+') as f:
        f.write(dedent('''
            "hello"
            def foo():
                foo() + os + sys
            import a, b, c
            a, c
        ''').lstrip())
        name = f.name
    cmd_output = pipe([BIN_DIR+"/tidy-imports", "-r", name])
    expected_cmd_output = dedent('''
        [PYFLYBY] {f.name}: removed unused 'import b'
        [PYFLYBY] {f.name}: added 'import os'
        [PYFLYBY] {f.name}: added 'import sys'
        [PYFLYBY] {f.name}: added mandatory 'from __future__ import absolute_import'
        [PYFLYBY] {f.name}: added mandatory 'from __future__ import division'
        [PYFLYBY] {f.name}: *** modified ***
    ''').strip().format(f=f)
    assert cmd_output == expected_cmd_output
    with open(name) as f:
        result = f.read()
    expected_result = dedent('''
        "hello"
        from __future__ import absolute_import, division

        import os
        import sys

        def foo():
            foo() + os + sys
        import a
        import c
        a, c
    ''').lstrip()
    assert result == expected_result
    os.unlink(name)


def test_tidy_imports_no_add_no_remove_1():
    input = dedent('''
        import a, b, c
        a, c, os, sys
    ''').lstrip()
    result = pipe([BIN_DIR+"/tidy-imports", "--no-add", "--no-remove"],
                  stdin=input)
    expected = dedent('''
        import a
        import b
        import c
        a, c, os, sys
    ''').strip()
    assert result == expected


def test_reformat_imports_1():
    input = dedent('''
        import zzt, megazeux
        from zzt import MEGAZEUX
        from ZZT import MEGAZEUX
        code()
        from megazeux import zzt
        from zzt import *
        import zzt as ZZT
        code() #x
        import zzt.zzt as zzt
        code()
        import zzt.foo as zzt
        code() #x
    ''').strip()
    result = pipe([BIN_DIR+"/reformat-imports"], stdin=input)
    expected = dedent('''
        from   ZZT                      import MEGAZEUX
        import megazeux
        import zzt
        code()
        from   megazeux                 import zzt
        import zzt as ZZT
        from   zzt                      import *
        code() #x
        from   zzt                      import zzt
        code()
        from   zzt                      import foo as zzt
        code() #x
    ''').strip()
    assert result == expected


def test_collect_imports_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(dedent('''
            "hello"
            from m1.m2 import f3, f4
            def f5(): pass
            def f6(): pass
            from m3.m4 import f6, f4
            import m1.m3
            f6, f7, m5, m7
            from m7 import *
        ''').lstrip())
        f.flush()
        result = pipe([BIN_DIR+"/collect-imports", f.name])
        expected = dedent('''
            from   m1.m2                    import f3, f4
            import m1.m3
            from   m3.m4                    import f4, f6
            from   m7                       import *
        ''').strip()
        assert result == expected


def test_collect_imports_include_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(dedent('''
            from m1.m2 import f3, f4
            from m3.m4 import f6, f4
            from m3.m5 import f7, f8
            import m1.m3
            from m7 import *
            from m1 import f9
            from .m1 import f5
            from m1x import f6
            import m1, m1y
        ''').lstrip())
        f.flush()
        result = pipe([BIN_DIR+"/collect-imports", f.name,
                       "--include=m1",
                       "--include=m3.m5"])
        expected = dedent('''
            import m1
            from   m1                       import f9
            from   m1.m2                    import f3, f4
            import m1.m3
            from   m3.m5                    import f7, f8
        ''').strip()
        assert result == expected


def test_collect_imports_include_dot_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(dedent('''
            from m1.m2 import f3, f4
            from m3.m4 import f6, f4
            import m1.m3
            from m7 import *
            from m1 import f9
            from .m1 import f5
            from m1x import f6
        ''').lstrip())
        f.flush()
        result = pipe([BIN_DIR+"/collect-imports", f.name, "--include=."])
        expected = dedent('''
            from   .m1                      import f5
        ''').strip()
        assert result == expected


def test_collect_exports_1():
    result = pipe([BIN_DIR+"/collect-exports", "fractions"])
    expected = dedent('''
        from   fractions                import Fraction, gcd
    ''').strip()
    assert result == expected


def test_find_import_1():
    result = pipe([BIN_DIR+"/find-import", "np"])
    expected = 'import numpy as np'
    assert result == expected


def test_find_import_bad_1():
    result = pipe([BIN_DIR+"/find-import", "omg_unknown_4223496"])
    expected = "[PYFLYBY] Can't find import for 'omg_unknown_4223496'"
    assert result == expected


def test_py_eval_1():
    result = pipe([BIN_DIR+"/py", "-c", "b64decode('aGVsbG8=')"])
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('aGVsbG8=')
        b'hello'
    """).strip()
    if PY2:
        expected = expected.replace("b'hello'", "'hello'")
    assert result == expected


def test_py_exec_1():
    result = pipe([BIN_DIR+"/py", "-c", "if 1: print(b64decode('aGVsbG8='))"])
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] if 1: print(b64decode('aGVsbG8='))
        b'hello'
    """).strip()
    if PY2:
        expected = expected.replace("b'hello'", "hello")
    assert result == expected


def test_py_name_1():
    result = pipe([BIN_DIR+"/py", "-c", "__name__"])
    expected = dedent("""
        [PYFLYBY] __name__
        '__main__'
    """).strip()
    assert result == expected


def test_py_argv_1():
    result = pipe([BIN_DIR+"/py", "-c", "sys.argv", "x", "y"])
    expected = dedent("""
       [PYFLYBY] import sys
       [PYFLYBY] sys.argv
       ['-c', 'x', 'y']
    """).strip()
    assert result == expected


def test_py_argv_2():
    result = pipe([BIN_DIR+"/py", "-c", "sys.argv", "--debug", "-x  x"])
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.argv
        ['-c', '--debug', '-x  x']
    """).strip()
    assert result == expected


def test_py_file_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write('print(sys.argv)\n')
        f.flush()
        result = pipe([BIN_DIR+"/py", f.name, "a", "b"])
    expected = dedent("""
        [PYFLYBY] import sys
        [%r, 'a', 'b']
    """).strip() % (f.name,)
    assert result == expected


def test_tidy_imports_query_no_change_1():
    input = dedent('''
        from __future__ import absolute_import, division
        import x1
        x1
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        # We expect no "Replace [y/N]" query, since nothing changed.
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert proc_output == b""
    assert output == input


def test_tidy_imports_query_y_1():
    input = dedent('''
        from __future__ import absolute_import, division
        import x1, x2
        x1
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("y\n")
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert b"[y/N] y" in proc_output
    expected = dedent("""
        from __future__ import absolute_import, division
        import x1
        x1
    """)
    assert output == expected


def test_tidy_imports_query_n_1():
    input = dedent('''
        from __future__ import absolute_import, division
        import x1, x2
        x1
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("n\n")
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert b"[y/N] n" in proc_output
    assert output == input


def test_tidy_imports_query_junk_1():
    input = dedent('''
        from __future__ import absolute_import, division
        import x1, x2
        x1
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("zxcv\n")
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert b"[y/N] zxcv" in proc_output
    assert b"Aborted" in proc_output
    assert output == input


# Note, these tests will fail if the system does not have both python2 and
# python3 in the PATH
def test_tidy_imports_py2_fallback():
    input = dedent('''
        import x

        def f(*args, x=1):
            pass
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("n\n")
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert b"removed unused 'import x'" in proc_output
    assert output == input
    if PY2:
        assert b"SyntaxError detected, falling back" in proc_output
    else:
        assert b"SyntaxError detected, falling back" not in proc_output

def test_tidy_imports_py3_fallback():
    input = dedent('''
        import x

        print 1
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [f.name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("n\n")
        child.expect(pexpect.EOF)
        with open(f.name) as f2:
            output = f2.read()
    proc_output = child.logfile.getvalue()
    assert b"removed unused 'import x'" in proc_output
    assert output == input
    if PY3:
        assert b"SyntaxError detected, falling back" in proc_output
    else:
        assert b"SyntaxError detected, falling back" not in proc_output

def test_tidy_imports_symlinks_default():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', [symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        # child.expect_exact(" [y/N]")
        # child.send("n\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"Error: %s appears to be a symlink" % symlink_name.encode("utf-8") in proc_output
    assert output == input
    assert symlink_output == input


def test_tidy_imports_symlinks_error():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', ['--symlinks=error', symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        # child.expect_exact(" [y/N]")
        # child.send("n\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"Error: %s appears to be a symlink" % symlink_name.encode("utf-8") in proc_output
    assert output == input
    assert symlink_output == input

def test_tidy_imports_symlinks_follow():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', ['--symlinks=follow', symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("y\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"Following symlink %s" % symlink_name.encode("utf-8") in proc_output
    assert 'import x' not in output
    assert 'import x' not in symlink_output

def test_tidy_imports_symlinks_skip():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', ['--symlinks=skip',
                                                        symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        # child.expect_exact(" [y/N]")
        # child.send("n\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"Skipping symlink %s" % symlink_name.encode("utf-8") in proc_output
    assert output == input
    assert symlink_output == input

def test_tidy_imports_symlinks_replace():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', ['--symlink=replace', symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        child.expect_exact(" [y/N]")
        child.send("y\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert not os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"Replacing symlink %s" % symlink_name.encode("utf-8") in proc_output
    assert output == input
    assert 'import x' not in symlink_output

def test_tidy_imports_symlinks_bad_argument():
    input = dedent('''
        import x
    ''')
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(input)
        f.flush()
        head, tail = os.path.split(f.name)
        symlink_name = os.path.join(head, 'symlink-' + tail)
        os.symlink(f.name, symlink_name)
        child = pexpect.spawn(BIN_DIR+'/tidy-imports', ['--symlinks=bad', symlink_name], timeout=5.0)
        child.logfile = BytesIO()
        # child.expect_exact(" [y/N]")
        # child.send("n\n")
        child.expect(pexpect.EOF)
        assert not os.path.islink(f.name)
        assert os.path.islink(symlink_name)
        with open(f.name) as f2:
            output = f2.read()
        with open(symlink_name) as f2:
            symlink_output = f2.read()

    proc_output = child.logfile.getvalue()
    assert b"error: --symlinks must be one of" in proc_output
    assert output == input
    assert symlink_output == input
