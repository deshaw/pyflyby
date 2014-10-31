# pyflyby/test_cmdline.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import os
import subprocess
import tempfile
from   textwrap                 import dedent

PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")
os.environ["PYFLYBY_PATH"] = os.path.join(PYFLYBY_HOME, "etc/pyflyby")
os.environ["PYFLYBY_KNOWN_IMPORTS_PATH"] = ""
os.environ["PYFLYBY_MANDATORY_IMPORTS_PATH"] = ""


def pipe(command, stdin=""):
    return subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE
    ).communicate(stdin)[0].strip()


def test_tidy_imports_stdin_1():
    result = pipe([BIN_DIR+"/tidy-imports"], stdin="os, sys")
    expected = dedent('''
        from __future__ import absolute_import, division, with_statement

        import os
        import sys

        os, sys
    ''').strip()
    assert result == expected


def test_tidy_imports_filename_action_print_1():
    with tempfile.NamedTemporaryFile(suffix=".py") as f:
        f.write(dedent('''
            # hello
            def foo():
                foo() + os + sys
        ''').lstrip())
        f.flush()
        result = pipe([BIN_DIR+"/tidy-imports", f.name])
        expected = dedent('''
            # hello
            from __future__ import absolute_import, division, with_statement

            import os
            import sys

            def foo():
                foo() + os + sys
        ''').strip()
        assert result == expected


def test_tidy_imports_filename_action_replace_1():
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
        f.write(dedent('''
            "hello"
            def foo():
                foo() + os + sys
            import a, b, c
            a, c
        ''').lstrip())
        name = f.name
    cmd_output = pipe([BIN_DIR+"/tidy-imports", "-r", name])
    assert cmd_output == ""
    with open(name) as f:
        result = f.read()
    expected = dedent('''
        "hello"
        from __future__ import absolute_import, division, with_statement

        import os
        import sys

        def foo():
            foo() + os + sys
        import a
        import c
        a, c
    ''').lstrip()
    assert result == expected
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
    with tempfile.NamedTemporaryFile(suffix=".py") as f:
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


def test_autopython_eval_1():
    result = pipe([BIN_DIR+"/autopython", "-c", "b64decode('aGVsbG8=')"])
    expected = "[AUTOIMPORT] from base64 import b64decode\n'hello'"
    assert result == expected


def test_autopython_exec_1():
    result = pipe([BIN_DIR+"/autopython", "-c", "print b64decode('aGVsbG8=')"])
    expected = "[AUTOIMPORT] from base64 import b64decode\nhello"
    assert result == expected


def test_autopython_name_1():
    result = pipe([BIN_DIR+"/autopython", "-c", "__name__"])
    expected = "'__main__'"
    assert result == expected


def test_autopython_argv_1():
    result = pipe([BIN_DIR+"/autopython", "-c", "sys.argv", "x", "y"])
    expected = "[AUTOIMPORT] import sys\n['-c', 'x', 'y']"
    assert result == expected


def test_autopython_file_1():
    fn = os.path.join(os.path.dirname(os.path.realpath(__file__)),
                      "helper_autoeval_foo.py")
    result = pipe([BIN_DIR+"/autopython", fn, "a", "b"])
    expected = "[AUTOIMPORT] import sys\n[%r, 'a', 'b']" % (fn,)
    assert result == expected
