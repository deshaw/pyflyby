# pyflyby/test_format.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   textwrap                 import dedent

from   pyflyby._format          import FormatParams, fill, pyfill


def test_fill_1():
    result = fill(["'hello world'", "'hello two'"],
                  prefix=("print ", "      "), suffix=(" \\", ""),
                  max_line_length=25)
    expected = "print 'hello world', \\\n      'hello two'\n"
    assert result == expected


def test_pyfill_1():
    result = pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"])
    expected = 'print foo.bar, baz, quux, quuuuux\n'
    assert result == expected


def test_pyfill_2():
    result = pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
                    FormatParams(max_line_length=15))
    expected = dedent("""
        print (foo.bar,
               baz,
               quux,
               quuuuux)
    """).lstrip()
    assert result == expected


def test_pyfill_3():
    result = pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
                    FormatParams(max_line_length=14, hanging_indent='always'))
    expected = dedent("""
        print (
            foo.bar,
            baz, quux,
            quuuuux)
    """).lstrip()
    assert result == expected


def test_pyfill_4():
    result = pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
                    FormatParams(max_line_length=14, hanging_indent='always'))
    expected = dedent("""
        print (
            foo.bar,
            baz, quux,
            quuuuux)
    """).lstrip()
    assert result == expected


def test_pyfill_5():
    result = pyfill('print ', ["foo.bar", "baz", "quux", "quuuuux"],
                    FormatParams(max_line_length=14, hanging_indent='auto'))
    expected = dedent("""
        print (
            foo.bar,
            baz, quux,
            quuuuux)
    """).lstrip()
    assert result == expected


def test_pyfill_hanging_indent_never_1():
    prefix = 'from   foo                      import '
    #          <---------------39 chars-------------->
    tokens = ['x23456789a123456789b123456789c123456789','z1','z2']
    params = FormatParams(max_line_length=79, hanging_indent='never')
    result = pyfill(prefix, tokens, params)
    expected = dedent("""
        from   foo                      import (x23456789a123456789b123456789c123456789,
                                                z1, z2)
    """).lstrip()
    assert result == expected


def test_pyfill_hanging_indent_always_1():
    prefix = 'from   foo                      import '
    #          <---------------39 chars-------------->
    tokens = ['x23456789a123456789b123456789c123456789','z1','z2']
    params = FormatParams(max_line_length=79, hanging_indent='always')
    result = pyfill(prefix, tokens, params)
    expected = dedent("""
        from   foo                      import (
            x23456789a123456789b123456789c123456789, z1, z2)
    """).lstrip()
    assert result == expected


def test_pyfill_hanging_indent_auto_yes_1():
    prefix = 'from   foo                      import '
    #          <---------------39 chars-------------->
    tokens = ['x23456789a123456789b123456789c123456789','z1','z2']
    params = FormatParams(max_line_length=79, hanging_indent='auto')
    result = pyfill(prefix, tokens, params)
    expected = dedent("""
        from   foo                      import (
            x23456789a123456789b123456789c123456789, z1, z2)
    """).lstrip()
    assert result == expected


def test_pyfill_hanging_indent_auto_no_1():
    prefix = 'from   foo                      import '
    #          <---------------38 chars-------------->
    tokens = ['x23456789a123456789b123456789c12345678','z1','z2']
    params = FormatParams(max_line_length=79, hanging_indent='auto')
    result = pyfill(prefix, tokens, params)
    expected = dedent("""
        from   foo                      import (x23456789a123456789b123456789c12345678,
                                                z1, z2)
    """).lstrip()
    assert result == expected
