# pyflyby/test_format.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

from   textwrap                 import dedent

from   pyflyby.format           import FormatParams, fill, pyfill


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
                    FormatParams(max_line_length=14))
    expected = dedent("""
        print (
            foo.bar,
            baz, quux,
            quuuuux)
    """).lstrip()
    assert result == expected
