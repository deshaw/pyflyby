# pyflyby/test_flags.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import ast


import pytest
import warnings

from   pyflyby._flags           import CompilerFlags


def skip_if_new_compiler_flags_values(func):

    return pytest.mark.skipif(
        int(CompilerFlags.print_function) != 0x10000,
        reason="Python flags values changes around Python == 3.8.2",
    )(func)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert int(CompilerFlags(0x18000)) == 0x18000


def test_CompilerFlags_zero_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert CompilerFlags() == CompilerFlags(None) == CompilerFlags(0)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_eqne_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert      CompilerFlags(0x18000) == CompilerFlags(0x18000)
        assert not (CompilerFlags(0x18000) != CompilerFlags(0x18000))
        assert CompilerFlags(0x18000) != CompilerFlags.type_comments
        assert not (CompilerFlags(0x18000) == CompilerFlags(0x10000))


@skip_if_new_compiler_flags_values
def test_CompilerFlags_eqne_other_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert CompilerFlags(0) != object()


@skip_if_new_compiler_flags_values
def test_CompilerFlags_names_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert CompilerFlags(0x18000).names == ("with_statement", "print_function")


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_int_multi_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert CompilerFlags(0x10000, 0x8000) == CompilerFlags(0x18000)
        assert CompilerFlags(0x10000, 0x8000, 0) == CompilerFlags(0x18000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_CompilerFlags_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = CompilerFlags(CompilerFlags(0x10000), CompilerFlags(0x8000))
        assert result == CompilerFlags(0x18000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_names_multi_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = CompilerFlags("with_statement", "print_function")
        assert result == CompilerFlags(0x18000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_names_single_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = CompilerFlags("with_statement")
        assert result == CompilerFlags(0x8000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_names_list_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = CompilerFlags(["with_statement", "print_function"])
        assert result == CompilerFlags(0x18000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_mixed_multi_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        result = CompilerFlags("print_function", 0x8000, CompilerFlags("division"))
        assert result == CompilerFlags(0x1a000)


@skip_if_new_compiler_flags_values
def test_CompilerFlags_from_ast_1():
    node = ast.parse("from __future__ import with_statement, print_function")
    result = CompilerFlags(node)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert result == CompilerFlags(0x18000)


def test_CompilerFlags_bad_name_1():
    with pytest.raises(ValueError):
        CompilerFlags("print_statement")


def test_CompilerFlags_bad_int_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        with pytest.raises(ValueError):
            CompilerFlags(1)


def test_CompilerFlags_bad_multi_int_1():
    with pytest.raises(ValueError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            CompilerFlags((0x8000 ^ 1), 0)
