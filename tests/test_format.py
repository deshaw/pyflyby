# pyflyby/test_format.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   textwrap                 import dedent

import pytest

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


def test_format_params_identity():
    p = FormatParams()
    assert FormatParams(p) is p


def test_format_params_none_arg():
    p = FormatParams(None)
    assert p.max_line_length is None
    assert p.indent == 4


def test_format_params_kwargs():
    p = FormatParams(indent=2, max_line_length=100)
    assert p.indent == 2
    assert p.max_line_length == 100


def test_format_params_merge_other_params():
    base = FormatParams(indent=8)
    merged = FormatParams(base, max_line_length=50)
    assert merged.indent == 8
    assert merged.max_line_length == 50


def test_format_params_bad_kwarg():
    with pytest.raises(ValueError):
        FormatParams(no_such_attr=1)


def test_format_params_repr():
    p = FormatParams(indent=2)
    r = repr(p)
    assert "FormatParams" in r


def test_pyfill_bad_hanging_indent():
    with pytest.raises(ValueError):
        pyfill('xxxxx ', ['aaaa', 'bbbb', 'cccc'],
               FormatParams(hanging_indent='maybe', max_line_length=10))


def test_pyfill_wrap_paren_false_raises():
    p = FormatParams()
    p.wrap_paren = False
    p.max_line_length = 1
    with pytest.raises(NotImplementedError):
        pyfill('x ', ['aaaaa', 'bbbbb', 'ccccc'], p)
