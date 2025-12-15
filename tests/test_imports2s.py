# pyflyby/test_imports2s.py
from __future__ import print_function

import tempfile

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import pytest
import sys
from   textwrap                 import dedent
import types

from   pyflyby._file            import FileText
from   pyflyby._format          import FormatParams
from   pyflyby._importdb        import ImportDB
from   pyflyby._imports2s       import (canonicalize_imports,
                                        fix_unused_and_missing_imports,
                                        reformat_import_statements,
                                        remove_broken_imports,
                                        replace_star_imports,
                                        transform_imports)
from   pyflyby._importstmt      import ImportFormatParams, ImportStatement
from   pyflyby._parse           import PythonBlock


def test_reformat_import_statements_1():
    input = PythonBlock(dedent('''
        from foo import bar2 as bar2x, bar1
        import foo.bar3 as bar3x
        import foo.bar4

        import foo.bar0 as bar0
    ''').lstrip(), filename="/foo/test_reformat_import_statements_1.py")
    output = reformat_import_statements(input)
    expected = PythonBlock(dedent('''
        import foo.bar4
        from foo import bar1, bar2 as bar2x, bar3 as bar3x

        from foo import bar0
    ''').lstrip(), filename="/foo/test_reformat_import_statements_1.py")
    assert output == expected


def test_reformat_import_statements_star_1():
    input = PythonBlock(dedent('''
        from mod1 import f1b
        from mod1 import f1a
        from mod2 import *
        from mod2 import f2b as F2B
        from mod2 import f2a as F2A
        from mod3 import f3b
        from mod3 import f3a
    ''').lstrip(), filename="/foo/test_reformat_import_statements_star_1.py")
    output = reformat_import_statements(input)
    expected = PythonBlock(dedent('''
        from mod1 import f1a, f1b
        from mod2 import *
        from mod2 import f2a as F2A, f2b as F2B
        from mod3 import f3a, f3b
    ''').lstrip(), filename="/foo/test_reformat_import_statements_star_1.py")
    assert output == expected


def test_reformat_import_statements_multi_star_1():
    input = PythonBlock(dedent('''
        from mod1 import *
        from mod2 import *
    ''').lstrip())
    output = reformat_import_statements(input)
    expected = PythonBlock(dedent('''
        from mod1 import *
        from mod2 import *
    ''').lstrip())
    assert output == expected


def test_reformat_import_statements_shadowed_1():
    input = PythonBlock(dedent('''
        import a, a2 as a, b, b2 as b, b, c2 as c, d2 as d
        from d import d
        import c
    ''').lstrip())
    output = reformat_import_statements(input)
    expected = PythonBlock(dedent('''
        import a2 as a
        import b
        import c
        from d import d
    ''').lstrip())
    assert output == expected


def test_reformat_continuation_comments_1():
    input = dedent('''
        import   b , a
        # x\\
        # y
    ''').lstrip()
    output = str(reformat_import_statements(input))
    expected = dedent('''
        import a
        import b
        # x\\
        # y
    ''').lstrip()
    assert expected == output


def test_fix_unused_and_missing_imports_1():
    input = PythonBlock(dedent('''
        from foo import m1, m2, m3, m4
        m2, m4, np.foo
    ''').lstrip(), filename="/foo/test_fix_unused_and_missing_imports_1.py")
    db = ImportDB("""
        import numpy as np
        __mandatory_imports__ = ["from __future__ import division"]
    """)
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from __future__ import division

        import numpy as np
        from foo import m2, m4
        m2, m4, np.foo
    ''').lstrip(), filename="/foo/test_fix_unused_and_missing_imports_1.py")
    assert output == expected


def test_fix_unused_and_missing_imports_unknown_1():
    input = PythonBlock(dedent('''
        os, sys
    ''').lstrip())
    db = ImportDB("import os")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        import os

        os, sys
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_known_different_1():
    input = PythonBlock(dedent('''
        from ma import a1, a2
        from mb import b1, b2
        a1, a2, a3, b1, b2, b3
    ''').lstrip())
    db = ImportDB("from MA import a1, a2, a3\nfrom MB import b1, b2, b3\n")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from MA import a3
        from MB import b3
        from ma import a1, a2
        from mb import b1, b2
        a1, a2, a3, b1, b2, b3
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_heuristic_1():
    input = PythonBlock(dedent('''
        from m1.a import f1
        from m2.a import f2
        from m3.a import f3
        f1, f2, f3, f4
    ''').lstrip())
    db = ImportDB("from m2.b import f4")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1.a import f1
        from m2.a import f2
        from m2.b import f4
        from m3.a import f3
        f1, f2, f3, f4
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_after_comments_1():
    input = PythonBlock(dedent('''
        # hello

        # there
        f1, f2
    ''').lstrip())
    db = ImportDB("from m1 import f1")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        # hello

        # there
        from m1 import f1

        f1, f2
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_after_docstring_1():
    input = PythonBlock(dedent('''
        """
        aaa
        """
        f1, f2
    ''').lstrip())
    db = ImportDB("from m1 import f1")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        """
        aaa
        """
        from m1 import f1

        f1, f2
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_after_docstring_cont_1():
    input = PythonBlock(dedent('''
        """
        aaa
        """ '\
        bbb'
        f1, f2
    ''').lstrip())
    db = ImportDB("from m1 import f1")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        """
        aaa
        """ '\
        bbb'
        from m1 import f1

        f1, f2
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_after_docstring_whitespace_1():
    input = PythonBlock(dedent('''
        """
        aaa
        """


        f1, f2
    ''').lstrip())
    db = ImportDB("from m1 import f1")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        """
        aaa
        """


        from m1 import f1

        f1, f2
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_insertion_comments_1():
    input = PythonBlock(dedent('''
        #c0
        from m1.y import m1yf
        #c1
        from m2.y import m2yf
        #c2
        from m3.y import m3yf
        #c3
        m1xf, m2xf, m3xf
        m1yf, m2yf, m3yf
        m1zf, m2zf, m3zf
    ''').lstrip())
    db = ImportDB("""
        from m1.x import m1xf
        from m1.y import m1yf
        from m1.z import m1zf
        from m2.x import m2xf
        from m2.y import m2yf
        from m2.z import m2zf
        from m3.x import m3xf
        from m3.y import m3yf
        from m3.z import m3zf
    """)
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        #c0
        from m1.x import m1xf
        from m1.y import m1yf
        from m1.z import m1zf
        #c1
        from m2.x import m2xf
        from m2.y import m2yf
        from m2.z import m2zf
        #c2
        from m3.x import m3xf
        from m3.y import m3yf
        from m3.z import m3zf
        #c3
        m1xf, m2xf, m3xf
        m1yf, m2yf, m3yf
        m1zf, m2zf, m3zf
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_compound_statements_1():
    input = PythonBlock(dedent('''
        import a, b; import c, d; g
        a, c; f
    ''').lstrip())
    db = ImportDB("""
        from m1 import f
        from m1 import g
    """)
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        import a
        import c
        from m1 import f, g
        g
        a, c; f
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_multiple_import_used_1():
    input = PythonBlock(dedent('''
        from m0 import f, x
        import z, x
        import y, z
        from m1 import h, f
        import x
        import x
        from m1 import f, f, g
        x, f
    ''').lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        import x
        from m1 import f
        x, f
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_shadowed_1():
    input = PythonBlock(dedent('''
        from m1 import f1, f2, f3
        def f2(): f1
    ''').lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import f1
        def f2(): f1
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_reassigned_first_reference_1():
    input = PythonBlock(dedent('''
        from bar import foo1, foo2
        foo2 = foo2 + 0
    ''').lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from bar import foo2
        foo2 = foo2 + 0
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_midfile_1():
    input = PythonBlock(dedent('''
        import m1, m2
        m2, m3
        import m4, m5
        m4, m6
    ''').lstrip())
    db = ImportDB("import m1, m2, m3, m4, m5, m6, m7")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        import m2
        import m3
        m2, m3
        import m4
        import m6
        m4, m6
    ''').lstrip())
    assert output == expected


@pytest.mark.parametrize(
    ("input_code", "expected_code"),
    [
        pytest.param(
            '''
                from m1 import f1, f2, f3
                def foo():
                    """
                      >>> f1 + f2 + f9
                    """
                    return None
            ''',
            '''
                from m1 import f1, f2
                def foo():
                    """
                      >>> f1 + f2 + f9
                    """
                    return None
            ''',
            id="simple_doctest",
        ),
        pytest.param(
            '''
                from m1 import f1, f2, f3
                def foo():
                    """
                      >>> f1 = 0
                      >>> f1 + f2 + f9
                    """
                    return None
            ''',
            '''
                from m1 import f2
                def foo():
                    """
                      >>> f1 = 0
                      >>> f1 + f2 + f9
                    """
                    return None
            ''',
            id="doctest_with_assignment",
            marks=pytest.mark.xfail,
        ),
    ],
)
def test_fix_unused_and_missing_imports_doctests(input_code, expected_code):
    input_code = dedent(input_code).lstrip()
    expected_code = dedent(expected_code).lstrip()
    input = PythonBlock(input_code)
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(expected_code)
    assert output == expected


def test_fix_unused_and_missing_imports_xref_1():
    input = PythonBlock(dedent('''
        from m1 import f1, f2, f3
        def foo():
            """
            Hello L{f1} C{f3}
            """
            return None
    ''').lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import f1, f3
        def foo():
            """
            Hello L{f1} C{f3}
            """
            return None
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_decorator_2():
    input = PythonBlock(dedent('''
        from m1 import d1, d2, d3
        @d1
        def f1(): pass
        @d9.d2
        def f9(): pass
    ''').lstrip())
    db = ImportDB("from m2 import d8, d9")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import d1
        from m2 import d9
        @d1
        def f1(): pass
        @d9.d2
        def f9(): pass
    ''').lstrip())
    assert output == expected




def test_fix_unused_and_missing_imports_funcall_1():
    input = PythonBlock(dedent('''
        from m1 import X1, X3, X9
        def F1(X1, X2=x2, X3=x3, *X4, **X5): X1, X5, x6, X9
        def F2(X7=x7): X7
        def F3(a1): a1
        def F4(): a1
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3, x4, x5, x6, x7, a1, a2")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import X9
        from m2 import a1, x2, x3, x6, x7
        def F1(X1, X2=x2, X3=x3, *X4, **X5): X1, X5, x6, X9
        def F2(X7=x7): X7
        def F3(a1): a1
        def F4(): a1
    ''').lstrip())
    assert output == expected


def test_fix_missing_imports_funcall_1():
    input = PythonBlock(dedent('''
        def F1(x1): x1, x2, y1
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3, x4")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m2 import x2

    ''').lstrip() + str(input))
    assert output == expected


def test_fix_missing_imports_funcall_and_really_missing_1():
    input = PythonBlock(dedent('''
        def F1(x1, x2, x3): x1, x2, x3, x4, y1
        x1
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3, x4, x5")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m2 import x1, x4

    ''').lstrip() + str(input))
    assert output == expected




def test_fix_missing_imports_local_1():
    input = PythonBlock(dedent('''
        def F1():
            x1 = 5
            x1, x2
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m2 import x2

        def F1():
            x1 = 5
            x1, x2
    ''').lstrip())
    assert output == expected


def test_fix_missing_imports_nonlocal_post_store_1():
    input = PythonBlock(dedent('''
        def F1():
            x1 = None
            def F2():
                x1, x2, x3, y1
            x2 = None
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3, x4, x5")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m2 import x3

    ''').lstrip() + str(input))
    assert output == expected


def test_fix_missing_imports_nonlocal_post_del_1():
    """
    Calling F2 after the deletion of x2 in the enclosing scope make no sens, it
    would trigger a:

    NameError: free variable 'x2' referenced before assignment in enclosing scope

    Regardless as to whether x2 is defines at module scope or not.

    Therefore we do not expect x2 to be imported
    """
    input = PythonBlock(dedent('''
        def F1():
            x1 = x2 = None
            def F2():
                x1, x2, x3, y1
            del x2
    ''').lstrip())
    db = ImportDB("from m2 import x1, x2, x3, x4")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m2 import x3

    ''').lstrip() + str(input))
    assert output == expected


def test_fix_unused_and_missing_imports_IfExp_1():
    input = PythonBlock(dedent('''
        x if y else z
    ''').lstrip())
    db = ImportDB("from m1 import w, x, y, z")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import x, y, z

        x if y else z
    ''').lstrip())
    assert output == expected


def test_fix_unused_and_missing_imports_ClassDef_1():
    input = PythonBlock(dedent('''
        @x1
        class x2(x3(x4), x5):
            @x6
            def x7(x8=x9): x10, x8
            def x11(): x11
    ''').lstrip())
    db = ImportDB("from m1 import x1,x2,x3,x4,x5,x6,x7,x8,x9,x10,x11,x12")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from m1 import x1, x10, x11, x3, x4, x5, x6, x9

        @x1
        class x2(x3(x4), x5):
            @x6
            def x7(x8=x9): x10, x8
            def x11(): x11
    ''').lstrip())
    assert output == expected


def test_fix_missing_imports_in_non_method():
    """
    unlike test_fix_unused_and_missing_imports_ClassDef_1
    Free standing functions can refer to themselves.

    Currently this will not work for closure defined in
    methods, as we'll see a class scope.

    See https://github.com/deshaw/pyflyby/issues/179
    """
    input = PythonBlock(
        dedent(
            """
            def selfref():
                selfref.execute = True
    """
        ).lstrip()
    )
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(
        dedent(
            """
            def selfref():
                selfref.execute = True
    """
        ).lstrip()
    )
    assert output == expected


@pytest.mark.parametrize('data',("""
    from __future__ import annotations

    class _TestCls():
        class WrappedFunction():
            pass

    class Popen():
        def test(self) -> Popen:
            return None""",
    """
    from __future__ import annotations

    class _TestCls():
        class WrappedFunction():
            pass

    class Popen():
        def test(self:Popen):
            return None
    """))
def test_fix_missing_imports_other_class(data):
    """
    This insert import for type annotations, only if a class is present before.

    See https://github.com/deshaw/pyflyby/issues/318
    """
    data = dedent(data)
    b = PythonBlock(data)
    db = ImportDB("from subprocess import Popen")
    output = fix_unused_and_missing_imports(b, db=db)
    expected = PythonBlock(data)
    assert output == expected


def test_fix_unused_and_missing_continutation_1():
    input = PythonBlock(dedent(r'''
        a#\
        b + '\
        c#' + d
    ''').lstrip())
    db = ImportDB("from m1 import a, b, c, d")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent(r'''
        from m1 import a, b, d

        a#\
        b + '\
        c#' + d
    ''').lstrip())
    assert output == expected


def test_fix_unused_import_future_is_not_unused_1():
    input = PythonBlock(dedent(r'''
        from __future__ import division
    ''').lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    assert output == input


def test_fix_unused_and_missing_print_function_1():
    input = PythonBlock(dedent(r'''
        from __future__ import print_function
        from m1 import print, m1a
        from m2.print import m2a, m2b
        m1a, m2a, m3a
    ''').lstrip())
    db = ImportDB(
        "from __future__ import print_function\n"
        "from print.m3 import m3a, m3b")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent(r'''
        from __future__ import print_function
        from m1       import m1a
        from m2.print import m2a
        from print.m3 import m3a
        m1a, m2a, m3a
    ''').lstrip())
    assert output == expected


def test_last_line_no_trailing_newline_1():
    input = PythonBlock("#x\ny")
    db = ImportDB("from Y import y")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        #x
        from Y import y

        y''').lstrip())
    assert output == expected


def test_last_line_comment_no_trailing_newline_1():
    input = PythonBlock("y\n#x")
    db = ImportDB("from Y import y")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from Y import y

        y
        #x''').lstrip())
    assert output == expected


def test_last_line_multistring_no_trailing_newline_1():
    input = PythonBlock(dedent('''
        """
        #x""", y # comment  ''').lstrip())
    db = ImportDB("from Y import y")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from Y import y

        """
        #x""", y # comment  ''').lstrip())
    assert output == expected


def test_last_line_escaped_string_no_trailing_newline_1():
    input = PythonBlock(dedent('''
        "\
        #x", y # comment  ''').lstrip())
    db = ImportDB("from Y import y")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from Y import y

        "\
        #x", y # comment  ''').lstrip())
    assert output == expected


def test_remove_broken_imports_1():
    input = PythonBlock(dedent('''
        import sys, os, omgdoesntexist_95421787, keyword
        from email.mime.audio import MIMEAudio, omgdoesntexist_8824165
        code()
    ''').lstrip(), filename="/foo/test_remove_broken_imports_1.py")
    output = remove_broken_imports(input)
    expected = PythonBlock(dedent('''
        import keyword
        import os
        import sys
        from email.mime.audio import MIMEAudio
        code()
    ''').lstrip(), filename="/foo/test_remove_broken_imports_1.py")
    assert output == expected


def test_replace_star_no_imports_found(capsys):
    m = types.ModuleType("fake_test_module_345490")
    sys.modules["fake_test_module_345490"] = m
    input = PythonBlock(dedent('''
        from fake_test_module_345490 import *
    ''').lstrip(), filename="/foo/test_replace_star_imports_2.py")
    _ = replace_star_imports(input)
    captured = capsys.readouterr()
    assert 'Traceback' not in captured.err


def test_replace_star_imports_os_issue_281(capsys):
    input = PythonBlock(dedent('''
        from os import *

        getcwd()
    ''').lstrip(), filename="/foo/test_replace_os_imports.py")
    _ = replace_star_imports(input)
    captured = capsys.readouterr()
    assert 'with' in captured.out and 'imports' in captured.out


@pytest.mark.skipif(
        sys.version_info >= (3,12),
        reason='Pyton 3.12 uses find_spec which does not work with injected modules')
def test_replace_star_imports_1():
    input = PythonBlock(dedent('''
        from mod1                    import f1
        from fake_test_module_345489 import *
        from mod2                    import f5
    ''').lstrip(), filename="/foo/test_replace_star_imports_1.py")
    m = types.ModuleType("fake_test_module_345489")
    m.__all__ = ['f1', 'f2', 'f3', 'f4', 'f5']
    sys.modules["fake_test_module_345489"] = m

    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write(f"__all__ = {m.__all__}")
        m.__file__ = f.name
        f.flush()
        output = replace_star_imports(input)

    expected = PythonBlock(dedent('''
        from fake_test_module_345489 import f1, f2, f3, f4
        from mod2                    import f5
    ''').lstrip(), filename="/foo/test_replace_star_imports_1.py")
    assert output == expected


def test_replace_star_imports_relative_1():
    # Not implemented (semi-intentionally), but at least don't crash.
    input = PythonBlock(dedent('''
        from .x import *
    ''').lstrip(), filename="/foo/test_replace_star_imports_relative_1.py")
    output = replace_star_imports(input)
    expected = PythonBlock(dedent('''
        from .x import *
    ''').lstrip(), filename="/foo/test_replace_star_imports_relative_1.py")
    assert output == expected


def test_replace_star_imports_unknown_module_1():
    input = PythonBlock(dedent('''
        from omgnonexistentmodule75085477 import *
    ''').lstrip())
    output = replace_star_imports(input)
    expected = PythonBlock(dedent('''
        from omgnonexistentmodule75085477 import *
    ''').lstrip())
    assert output == expected


def test_transform_imports_1():
    input = PythonBlock(dedent('''
        from m import x
        from m import x as X
        import m.x
        print(m.x, m.xx)
    ''').lstrip(), filename="/foo/test_transform_imports_1.py")
    output = transform_imports(input, {"m.x": "m.y.z"})
    expected = PythonBlock(dedent('''
        import m.y.z
        from m.y import z as X, z as x
        print(m.y.z, m.xx)
    ''').lstrip(), filename="/foo/test_transform_imports_1.py")
    assert output == expected


def test_canonicalize_imports_1():
    input = PythonBlock(
        dedent(
            """
        from very_very_very_long_named_package.very_long_named_module \\
                                import(small_class, very_large_named_class as small_name)
        from m import x
        from m import x as X
        import m.x
        print(m.x, m.xx)
    """
        ).lstrip(),
        filename="/foo/test_transform_imports_1.py",
    )
    db = ImportDB(
        """
        __canonical_imports__ = {"m.x": "m.y.z"}
    """
    )
    output = canonicalize_imports(input, db=db)
    expected = PythonBlock(
        dedent("""
        import m.y.z
        from m.y                                                      import (z as X,
                                                                              z as x)
        from very_very_very_long_named_package.very_long_named_module import (small_class,
                                                                              very_large_named_class as small_name)
        print(m.y.z, m.xx)
        """).lstrip(),
        filename="/foo/test_transform_imports_1.py",
    )
    assert output == expected


def test_canonicalize_imports_f_string_1():
    input = PythonBlock(dedent('''
        a = 1
        print(f"{a:2d}")
    ''').lstrip(), filename="/foo/test_canonicalize_imports_f_string_1.py")
    db = ImportDB("""
    """)
    output = canonicalize_imports(input, db=db)
    expected = PythonBlock(dedent('''
        a = 1
        print(f"{a:2d}")
    ''').lstrip(), filename="/foo/test_canonicalize_imports_f_string_1.py")
    assert output == expected

def test_empty_file_1():
    input = PythonBlock('', filename="/foo/test_empty_file_1.py")
    db = ImportDB("")
    output = canonicalize_imports(input, db=db)
    expected = PythonBlock('', filename="/foo/test_empty_file_1.py")
    assert output == expected


def test_empty_file_mandatory_1():
    input = PythonBlock('', filename="/foo/test_empty_file_mandatory_1.py")
    db = ImportDB("__mandatory_imports__ = ['from aa import cc,bb']")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock('from aa import bb, cc\n\n',
                           filename="/foo/test_empty_file_mandatory_1.py")
    assert output == expected


def test_future_flags_1():
    input = PythonBlock(dedent('''
        from __future__ import print_function

        print("", file=sys.stdout)
    ''').lstrip())
    db = ImportDB("import os, sys")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from __future__ import print_function
        import sys

        print("", file=sys.stdout)
    ''').lstrip())
    assert output == expected


def test_with_1():
    input = PythonBlock(dedent('''
        with   closing(open("/etc/passwd")) as f:
            pass
    ''').lstrip())
    db = ImportDB("from contextlib import closing")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        from contextlib import closing

        with   closing(open("/etc/passwd")) as f:
            pass
    ''').lstrip())
    assert expected == output




def test_fix_unused_imports_dunder_file_1(capsys):
    input = PythonBlock(dedent('''
        __file__, __asdf__
    '''))
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(dedent('''
        __file__, __asdf__
    '''))
    assert expected == output
    out, err = capsys.readouterr()
    assert "undefined name '__asdf__'"     in out
    assert "undefined name '__file__'" not in out
    assert not err


def test_x_shadow_comprehension(capsys):
    input = PythonBlock(
        dedent(
            """
    def f():
        x = 1
        y = [x for _ in range(5)]
        del x
    """
        )
    )
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input, db=db)
    out, err = capsys.readouterr()
    assert output == input
    assert "undefined name 'x'" not in out
    assert not err

@pytest.mark.parametrize(
    ("input_code", "expected_code", "db_str"),
    [
        pytest.param(
            '''
        from m1 import X1, X2
        def F1(X1): X1, X2
    ''',
            '''
        from m1 import X2
        def F1(X1): X1, X2
    ''',
            "",
            id="funcall",
        ),
        pytest.param(
            '''
        from m1 import X1, X2
        def F1():
            X1 = 5
            X1, X2
    ''',
            '''
        from m1 import X2
        def F1():
            X1 = 5
            X1, X2
    ''',
            "",
            id="local",
        ),
        pytest.param(
            '''
        import foo1, foo2, foo1, foo1
        import foo1, foo2, foo3
        foo1, foo2
    ''',
            '''
        import foo1
        import foo2
        foo1, foo2
    ''',
            "",
            id="repeated",
        ),
        pytest.param(
            '''
        import m2.y
        m2.x + m2.y + m3.x
    ''',
            '''
        import m2.y
        import m3
        m2.x + m2.y + m3.x
    ''',
            "import m2, m3, m4",
            id="submodule",
        ),
        pytest.param(
            '''
        import m2.y as m2y
        m2.x + m2y + m3.x
    ''',
            '''
        import m2
        import m3
        from m2 import y as m2y
        m2.x + m2y + m3.x
    ''',
            "import m2, m3, m4",
            id="submodule_importas",
        ),
    ],
)
def test_fix_unused_imports_basic(input_code, expected_code, db_str):
    """Test basic unused import removal scenarios."""
    input_code = dedent(input_code).lstrip()
    expected_code = dedent(expected_code).lstrip()
    input = PythonBlock(input_code)
    db = ImportDB(db_str)
    output = fix_unused_and_missing_imports(input, db=db)
    expected = PythonBlock(expected_code)
    assert output == expected


@pytest.mark.parametrize(
    ("max_line_length", "expected_output"),
    [
        pytest.param(
            100,
            dedent('''
                from math import (cos, cosh, factorial, floor, log, log10, nextafter, radians, remainder, sin, sinh,
                                  tan, tanh)
                assert [sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians]
            ''').lstrip(),
            id="width_100",
        ),
        pytest.param(
            200,
            dedent('''
                from math import cos, cosh, factorial, floor, log, log10, nextafter, radians, remainder, sin, sinh, tan, tanh
                assert [sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians]
            ''').lstrip(),
            id="width_200",
        ),
    ],
)
def test_reformat_import_statements_respect_width(tmp_path, max_line_length, expected_output):
    """Test that tidy-imports with a max line length correctly wraps imports."""
    filename = str(tmp_path / "test_reformat_import_statements_respect_width")
    input = PythonBlock(dedent('''
        from math import sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians
        assert [sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians]
    ''').lstrip(), filename=filename)
    output = reformat_import_statements(input, FormatParams(max_line_length=max_line_length))
    expected = PythonBlock(expected_output, filename=filename)
    assert output == expected


def test_reformat_import_statements_respect_width_default_none(tmp_path):
    """Test that tidy-imports with no specified width matches the default width."""
    filename = str(tmp_path / "test_reformat_import_statements_respect_width_default")
    input = PythonBlock(dedent('''
        from math import sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians
        assert [sin,cos,tan,sinh,cosh,tanh,log,floor,log10,remainder,factorial,nextafter,radians]
    ''').lstrip(), filename=filename)
    assert reformat_import_statements(
        input,
        FormatParams(max_line_length=None),
    ) == reformat_import_statements(
        input,
        FormatParams(max_line_length=FormatParams.max_line_length_default),
    )

@pytest.mark.parametrize(
    ("text"),
    [
        "import foo # test comment # more text",
        "from foo import bar, bar2 # test comment",
        "from foo import bar, bar2, baz, quux, abc, defg, lmo, pqr, nmp, qrs, ghi, jkl # test comment",
        "from foo import (\n    bar # test comment\n)",
        "from foo import (\n\n    bar # test comment\n)",
        "from foo import ( # test comment\n    bar\n)",
        "from foo import ( # test comment\n    bar,\n)",
        "from foo import (\n    bar, # test comment\n)",
        "from foo import (\n    bar\n) # test comment\n",
        "from foo import (\n    bar, # test comment\n    bar2\n)",
        "from foo import (\n    bar,\n    bar2 # test comment\n)",
        "import foo # test comment",
        "from foo import bar # test comment",
        "import foo",
        "import foo as bar",
        "from foo import bar, bar2",
        "from foo import bar, bar2, baz, quux, abc, defg, lmo, pqr, nmp, qrs, ghi, jkl",
    ]
)
def test_fumi(text):
    """Test fix_unused_and_missing_imports keeps 1-line comments for single aliases."""
    kwargs = {
        'params': ImportFormatParams(
            align_imports=(32,),
            from_spaces=3,
            separate_from_imports=False,
            max_line_length=None,
            use_black=False,
            align_future=False,
            hanging_indent="never",
        ),
        'add_missing': True,
        'remove_unused': 'AUTOMATIC',
        'add_mandatory': True,
    }

    imp_stmt = ImportStatement._from_str(text)

    # Insert all the imports in the text as variables in the fake code block,
    # so they don't get removed when calling fix_unused_and_missing_imports
    fake_code_block = (
        "\n\nif __name__ == '__main__':\n    "
        + '\n    '.join(imp.import_as for imp in imp_stmt.imports)
    )
    fixed = str(
        fix_unused_and_missing_imports(
            FileText(text + fake_code_block),
            **kwargs
        )
    )

    # Only single alias imports have comments preserved
    if "#" in text and len(imp_stmt.aliases) == 1:
        assert "test comment" in fixed or "test comment # more text" in fixed
    else:
        assert '#' not in fixed
        assert 'test_comment' not in fixed
