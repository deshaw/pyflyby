# pyflyby/test_flags.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import ast

from   six                      import PY3

import pytest

from   pyflyby._flags           import CompilerFlags


def test_CompilerFlags_1():
    assert int(CompilerFlags(0x18000)) == 0x18000


def test_CompilerFlags_zero_1():
    assert CompilerFlags() == CompilerFlags(None) == CompilerFlags(0)


def test_CompilerFlags_eqne_1():
    assert      CompilerFlags(0x18000) == CompilerFlags(0x18000)
    assert not (CompilerFlags(0x18000) != CompilerFlags(0x18000))
    assert      CompilerFlags(0x18000) != CompilerFlags(0x10000)
    assert not (CompilerFlags(0x18000) == CompilerFlags(0x10000))


def test_CompilerFlags_eqne_other_1():
    assert CompilerFlags(0) != object()


def test_CompilerFlags_names_1():
    assert CompilerFlags(0x18000).names == ("with_statement", "print_function")


def test_CompilerFlags_from_int_multi_1():
    assert CompilerFlags(0x10000, 0x8000) == CompilerFlags(0x18000)
    assert CompilerFlags(0x10000, 0x8000, 0) == CompilerFlags(0x18000)


def test_CompilerFlags_from_CompilerFlags_1():
    result = CompilerFlags(CompilerFlags(0x10000), CompilerFlags(0x8000))
    assert result == CompilerFlags(0x18000)


def test_CompilerFlags_from_names_multi_1():
    result = CompilerFlags("with_statement", "print_function")
    assert result == CompilerFlags(0x18000)


def test_CompilerFlags_from_names_single_1():
    result = CompilerFlags("with_statement")
    assert result == CompilerFlags(0x8000)


def test_CompilerFlags_from_names_list_1():
    result = CompilerFlags(["with_statement", "print_function"])
    assert result == CompilerFlags(0x18000)


def test_CompilerFlags_from_mixed_multi_1():
    result = CompilerFlags("print_function", 0x8000, CompilerFlags("division"))
    assert result == CompilerFlags(0x1a000)


def test_CompilerFlags_from_ast_1():
    node = ast.parse("from __future__ import with_statement, print_function")
    result = CompilerFlags(node)
    assert result == CompilerFlags(0x18000)


@pytest.mark.skipif(
    PY3,
    reason="print function is not invalid syntax in Python 3.")
def test_CompilerFlags_compile_1():
    # Should raise SyntaxError:
    with pytest.raises(SyntaxError):
        compile("print('x', file=None)", "?", "exec", flags=0, dont_inherit=1)
    # Shouldn't raise SyntaxError:
    compile("print('x', file=None)", "?", "exec", flags=CompilerFlags("print_function"), dont_inherit=1)


def test_CompilerFlags_bad_name_1():
    with pytest.raises(ValueError):
        CompilerFlags("print_statement")


def test_CompilerFlags_bad_int_1():
    with pytest.raises(ValueError):
        CompilerFlags(1)


def test_CompilerFlags_bad_multi_int_1():
    with pytest.raises(ValueError):
        CompilerFlags(0x8000^1, 0)
