# pyflyby/test_cmdline.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   io                       import BytesIO
import os
import pexpect
import subprocess
import sys
import tempfile
from   textwrap                 import dedent

from   pyflyby._cmdline         import _get_pyproj_toml_config
from   pyflyby._util            import CwdCtx, EnvVarCtx

import pytest

if sys.version_info < (3, 11):
    from tomli import loads
else:
    from tomllib import loads


PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")


python = sys.executable

def pipe(command, stdin="", cwd=None, env=None):
    return subprocess.Popen(
        [python] + command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env
    ).communicate(stdin.encode('utf-8'))[0].decode('utf-8').strip()


def test_tidy_imports_stdin_1():
    result = pipe([BIN_DIR+"/tidy-imports"], stdin="os, sys")
    expected = dedent('''
        [PYFLYBY] /dev/stdin: added 'import os'
        [PYFLYBY] /dev/stdin: added 'import sys'
        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


def test_tidy_imports_quiet_1():
    result = pipe([BIN_DIR+"/tidy-imports", "--quiet"], stdin="os, sys")
    expected = dedent('''
        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


def test_tidy_imports_log_level_1():
    with EnvVarCtx(PYFLYBY_LOG_LEVEL="WARNING"):
        result = pipe([BIN_DIR + "/tidy-imports"], stdin="os, sys")
        expected = dedent(
            """
            import os
            import sys

            os, sys
        """
        ).strip()
        assert result == expected


def test_tidy_imports_filename_action_print_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+") as f:
        f.write(
            dedent(
                """
            # hello
            def foo():
                foo() + os + sys
        """
            ).lstrip()
        )
        f.flush()
        result = pipe([BIN_DIR + "/tidy-imports", f.name])
        expected = (
            dedent(
                """
            [PYFLYBY] {f.name}: added 'import os'
            [PYFLYBY] {f.name}: added 'import sys'
            # hello
            import os
            import sys

            def foo():
                foo() + os + sys
        """
            )
            .strip()
            .format(f=f)
        )
        assert result == expected


def test_unsafe_cwd():
    with tempfile.TemporaryDirectory() as d:
        from pathlib import Path

        p = Path(d)
        unsafe = p / "foo#bar" / "foo#qux"
        unsafe.mkdir(parents=True)
        result = pipe([BIN_DIR + "/py"], cwd=unsafe, stdin="os")
        assert "Unsafe" not in result
        assert result == "[PYFLYBY] import os"


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
        [PYFLYBY] {f.name}: *** modified ***
    ''').strip().format(f=f)
    assert cmd_output == expected_cmd_output
    with open(name) as f:
        result = f.read()
    expected_result = dedent('''
        "hello"
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
    result = pipe([BIN_DIR + "/collect-exports", "fractions"])
    expected = dedent(
        """
        from   fractions                import Fraction
    """
    ).strip()

    assert result == expected

def test_collect_exports_module_1():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'test_mod'))
        with open(os.path.join(d, 'test_mod', '__init__.py'), 'w') as f:
            f.write(dedent('''
                # test_mod/__init__.py

                from .submod import e

                _private = 0
                a = 1
                b = 2
                c = 3
                d = 4

                print("The test_mod code is being executed")

            ''').lstrip())
        with open(os.path.join(d, 'test_mod', 'submod.py'), 'w') as f:
            f.write(dedent('''
                # test_mod/submod.py

                e = 5
                f = 6
            ''').lstrip())

        env = os.environ.copy()
        env['PYTHONPATH'] = '.'
        result = pipe([BIN_DIR+"/collect-exports", 'test_mod'], cwd=d, env=env)
        # TODO: Make this work statically
        expected = dedent('''
            The test_mod code is being executed
            from   test_mod                 import a, b, c, d, e
        ''').strip()
        assert result == expected


def test_collect_exports_module_2():
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, 'test_mod'))
        with open(os.path.join(d, 'test_mod', '__init__.py'), 'w') as f:
            f.write(dedent('''
                # test_mod/__init__.py

                __all__ = ['a', 'b', 'e']

                from .submod import e

                _private = 0
                a = 1
                b = 2
                c = 3
                d = 4

                print("The test_mod code is being executed")

            ''').lstrip())
        with open(os.path.join(d, 'test_mod', 'submod.py'), 'w') as f:
            f.write(dedent('''
                # test_mod/submod.py

                e = 5
                f = 6
            ''').lstrip())

        env = os.environ.copy()
        env['PYTHONPATH'] = '.'
        result = pipe([BIN_DIR+"/collect-exports", 'test_mod'], cwd=d, env=env)

        expected = dedent('''
            from   test_mod                 import a, b, e
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
    assert result == expected


def test_py_exec_1():
    result = pipe([BIN_DIR+"/py", "-c", "if 1: print(b64decode('aGVsbG8='))"])
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] if 1: print(b64decode('aGVsbG8='))
        b'hello'
    """).strip()
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', f.name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', f.name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', f.name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', f.name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', symlink_name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', '--symlinks=error', symlink_name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', '--symlinks=follow', symlink_name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', '--symlinks=skip',
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', '--symlink=replace', symlink_name], timeout=5.0)
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
        child = pexpect.spawn(python, [BIN_DIR+'/tidy-imports', '--symlinks=bad', symlink_name], timeout=5.0)
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


def test_debug_filetype_with_py():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(dedent("""
            sys.argv
        """).lstrip())
        f.flush()
        command = [BIN_DIR+"/py", "--debug", f.name]

        output_result = b""
        child = pexpect.spawn(' '.join(command), timeout=5)
        child.expect('ipdb>')
        output_result += child.before
        child.sendline('c')
        output_result += child.before
        child.expect(pexpect.EOF)
        output_result += child.before

        expected = "Entering debugger.  Use 'n' to step, 'c' to run, 'q' to stop."
        assert expected in output_result.decode()


@pytest.mark.skip(reason='disable sorting for time being until 287 fixed')
def test_tidy_imports_sorting():
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+") as f:
        f.write(
            dedent(
                """
            from very_very_very_long_named_package.very_long_named_module \
                                import(small_class, very_large_named_class as small_name)
            import numpy

            from pkg1.mod1 import foo
            from pkg1.mod2 import bar
            from pkg2 import baz
            import yy

            from pkg1.mod1 import foo2
            from pkg1.mod3 import quux
            from pkg2 import baar
            import sympy
            import zz


            zz.foo()
            bar()
            quux()
            foo2()
            yy.f()
            bar()
            foo()
            numpy.arange()
            baz
            baar
            sympy
            small_class
            small_name
        """
            ).lstrip()
        )
        f.flush()
        result = pipe([BIN_DIR + "/tidy-imports", f.name])
        expected = (
            dedent(
                """
            import numpy

            from   pkg1.mod1                import foo, foo2
            from   pkg1.mod2                import bar
            from   pkg1.mod3                import quux

            from   pkg2                     import baar, baz
            import sympy
            from   very_very_very_long_named_package.very_long_named_module \\
                                            import (small_class,
                                                    very_large_named_class as small_name)
            import yy
            import zz

            zz.foo()
            bar()
            quux()
            foo2()
            yy.f()
            bar()
            foo()
            numpy.arange()
            baz
            baar
            sympy
            small_class
            small_name
        """
            )
            .strip()
            .format(f=f)
        )
        assert result == expected


def test_tidy_imports_forward_references():
    with tempfile.TemporaryDirectory() as temp_dir:
        foo = os.path.join(temp_dir, "foo.py")
        with open(foo, "w") as foo_fp:
            foo_fp.write(
                dedent(
                    """
                from __future__ import annotations

                class A:
                    param1: str
                    param2: B


                class B:
                    param1: str
            """
                ).lstrip()
            )
            foo_fp.flush()

        dot_pyflyby = os.path.join(temp_dir, ".pyflyby")
        with open(dot_pyflyby, "w") as dot_pyflyby_fp:
            dot_pyflyby_fp.write(
                dedent(
                    """
                from foo import A, B
            """
                ).lstrip()
            )
            dot_pyflyby_fp.flush()
        with CwdCtx(temp_dir):
            result = pipe(
                [BIN_DIR + "/tidy-imports", foo_fp.name],
                env={"PYFLYBY_PATH": dot_pyflyby},
            )

            expected = dedent(
                """
                from __future__ import annotations

                class A:
                    param1: str
                    param2: B


                class B:
                    param1: str
            """
            ).strip()
        assert result == expected


@pytest.mark.parametrize(
    "pyproject_text",
    [
        r'''[tool.tox.env_run_base]
commands = [["{tox_root}{/}run_pytest.py", {replace = "posargs", default = ["-cvv"], extend = true}]]''',
        r'''[build-system]
requires = ["setuptools >= 61.0"]
build-backend = "setuptools.build_meta"

[tool.mypy]
files = ['lib']
#warn_incomplete_stub = false
warn_unused_configs = true
#ignore_missing_imports = true
follow_imports = 'silent'
# disallow_untyped_defs = true
# ignore_errors = false
# ignore_missing_imports = false
# disallow_untyped_calls = true
# disallow_incomplete_defs = true
# check_untyped_defs = true
# disallow_untyped_decorators = true
warn_redundant_casts = true
exclude = '(?x)(_dbg\.py|_py\.py)'

[[tool.mypy.overrides]]
module = [
    "pyflyby._interactive",
]
ignore_errors = true
'''
    ]
)
def test_tidy_imports_toml(tmp_path, pyproject_text):
    """Test that tidy-imports works with a pyproject.toml that has mixed array types."""
    with open(tmp_path / "pyproject.toml", 'w') as f:
        f.write(pyproject_text)

    result = pipe([BIN_DIR+"/tidy-imports", "--quiet"], stdin="os, sys", cwd=tmp_path)
    expected = dedent('''
        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


@pytest.mark.parametrize(
    "pyproject_text",
    [
        r'''[tool.tox.env_run_base]
commands = [["{tox_root}{/}run_pytest.py", {replace = "posargs", default = ["-cvv"], extend = true}]]''',
        r'''[build-system]
requires = ["setuptools >= 61.0"]
build-backend = "setuptools.build_meta"

[tool.mypy]
files = ['lib']
#warn_incomplete_stub = false
warn_unused_configs = true
#ignore_missing_imports = true
follow_imports = 'silent'
# disallow_untyped_defs = true
# ignore_errors = false
# ignore_missing_imports = false
# disallow_untyped_calls = true
# disallow_incomplete_defs = true
# check_untyped_defs = true
# disallow_untyped_decorators = true
warn_redundant_casts = true
exclude = '(?x)(_dbg\.py|_py\.py)'

[[tool.mypy.overrides]]
module = [
    "pyflyby._interactive",
]
ignore_errors = true
'''
    ]
)
def test_load_pyproject_toml(tmp_path, pyproject_text):
    """Test that a pyproject.toml that has mixed array types can be loaded."""
    with open(tmp_path / "pyproject.toml", 'w') as f:
        f.write(pyproject_text)

    os.chdir(tmp_path)
    assert _get_pyproj_toml_config() == loads(pyproject_text)


def test_load_no_pyproject_toml(tmp_path):
    """Test that a directory without a pyproject.toml is correctly handled."""
    os.chdir(tmp_path)
    assert _get_pyproj_toml_config() is None


def test_pyproject_unaligned(tmp_path):
    """Test that having an unaligned option in pyproject.toml works as intended."""
    with open(tmp_path / 'pyproject.toml', 'w') as f:
        f.write(
            dedent(
                """
                [tool.pyflyby]
                remove_unused = false
                add_mandatory = false
                unaligned = true
                """
            )
        )

    with open(tmp_path / "foo.py", 'w') as f:
        f.write(
            dedent(
                """
                from math import pi
                import numpy
                from os import open
                import pandas
                from urllib import request
                """
            )
        )

    child = pexpect.spawn(
        python,
        [BIN_DIR + "/tidy-imports", "./"],
        timeout=5.0,
        cwd=tmp_path,
        logfile=BytesIO(),
    )
    child.expect_exact("foo.py? [y/N]")
    child.send("y\n")
    child.expect(pexpect.EOF)

    with open(tmp_path / "foo.py") as f:
        assert f.read() == dedent(
            """
            import numpy
            import pandas
            from math import pi
            from os import open
            from urllib import request
            """
        )


def test_no_unaligned(tmp_path):
    """Test that not having an unaligned option in pyproject.toml works as intended."""
    with open(tmp_path / 'pyproject.toml', 'w') as f:
        f.write(
            dedent(
                """
                [tool.pyflyby]
                remove_unused = false
                add_mandatory = false
                """
            )
        )

    with open(tmp_path / "foo.py", 'w') as f:
        f.write(
            dedent(
                """
                from math import pi
                import numpy
                from os import open
                import pandas
                from urllib import request
                """
            )
        )

    child = pexpect.spawn(
        python,
        [BIN_DIR + "/tidy-imports", "./"],
        timeout=5.0,
        cwd=tmp_path,
        logfile=BytesIO(),
    )
    child.expect_exact("foo.py? [y/N]")
    child.send("y\n")
    child.expect(pexpect.EOF)

    with open(tmp_path / "foo.py") as f:
        assert f.read() == dedent(
            """
            from   math                     import pi
            import numpy
            from   os                       import open
            import pandas
            from   urllib                   import request
            """
        )


def test_tidy_imports_exclude_pyproject(tmp_path):
    """Test that a pyproject.toml can be used to exclude files for tidy-imports."""
    with open(tmp_path / "pyproject.toml", 'w') as f:
        f.write(
            dedent(
                """
                [tool.pyflyby.tidy-imports]
                exclude = [
                    'foo.py',
                    'bar/*.py',
                ]
                """
            )
        )

    (tmp_path / "bar").mkdir()
    (tmp_path / "baz" / "blah").mkdir(parents=True)

    txt = dedent(
        """
        # hello
        def foo():
            foo() + os + sys
        """
    )
    for path in [
        tmp_path / "foo.py",
        tmp_path / "what.py",
        tmp_path / "bar" / "foo2.py",
        tmp_path / "baz" / "foo3.py",
    ]:
        with open(path, "w") as f:
            f.write(txt)

    child = pexpect.spawn(
        python,
        [BIN_DIR+'/tidy-imports', './'],
        timeout=5.0,
        cwd=tmp_path,
        logfile=BytesIO()
    )
    child.expect_exact("baz/foo3.py? [y/N]")
    child.send("y\n")
    child.expect_exact("what.py? [y/N]")
    child.send("y\n")
    child.expect(pexpect.EOF)

    # Check that the tidy-imports output has log messages about exclusion patterns
    output = child.logfile.getvalue().decode()
    assert "bar/foo2.py matches exclusion pattern: bar/*.py" in output
    assert "foo.py matches exclusion pattern: foo.py" in output

    # Check that the two modified files have imports
    with open(tmp_path / "baz" / "foo3.py") as f:
        foo3 = f.read()

    with open(tmp_path / "what.py") as f:
        what = f.read()

    expected = dedent(
        """
        # hello
        import os
        import sys

        def foo():
            foo() + os + sys
        """
    )
    assert foo3 == expected
    assert what == expected

    # Check that the two unmodified files don't have imports
    with open(tmp_path / "foo.py") as f:
        foo = f.read()

    with open(tmp_path / "bar" / "foo2.py") as f:
        foo2 = f.read()

    assert foo == txt
    assert foo2 == txt


def test_tidy_imports_exclude_arg(tmp_path):
    """Test that a command line arg can be used to exclude files for tidy-imports."""
    (tmp_path / "bar").mkdir()
    (tmp_path / "baz" / "blah").mkdir(parents=True)

    txt = dedent(
        """
        # hello
        def foo():
            foo() + os + sys
        """
    )
    for path in [
        tmp_path / "foo.py",
        tmp_path / "what.py",
        tmp_path / "bar" / "foo2.py",
        tmp_path / "baz" / "foo3.py",
    ]:
        with open(path, "w") as f:
            f.write(txt)

    child = pexpect.spawn(
        python,
        [
            BIN_DIR + "/tidy-imports",
            "./",
            "--exclude",
            "foo.py",
            "--exclude",
            "bar/*.py",
        ],
        timeout=5.0,
        cwd=tmp_path,
        logfile=BytesIO(),
    )
    child.expect_exact("baz/foo3.py? [y/N]")
    child.send("y\n")
    child.expect_exact("what.py? [y/N]")
    child.send("y\n")
    child.expect(pexpect.EOF)

    # Check that the tidy-imports output has log messages about exclusion patterns
    output = child.logfile.getvalue().decode()
    assert "bar/foo2.py matches exclusion pattern: bar/*.py" in output
    assert "foo.py matches exclusion pattern: foo.py" in output

    # Check that the two modified files have imports
    with open(tmp_path / "baz" / "foo3.py") as f:
        foo3 = f.read()

    with open(tmp_path / "what.py") as f:
        what = f.read()

    expected = dedent(
        """
        # hello
        import os
        import sys

        def foo():
            foo() + os + sys
        """
    )
    assert foo3 == expected
    assert what == expected

    # Check that the two unmodified files don't have imports
    with open(tmp_path / "foo.py") as f:
        foo = f.read()

    with open(tmp_path / "bar" / "foo2.py") as f:
        foo2 = f.read()

    assert foo == txt
    assert foo2 == txt
