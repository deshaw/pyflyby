# pyflyby/test_flags.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import ast


import pytest
import warnings

from   pyflyby._flags           import CompilerFlags


def test_CompilerFlags_zero_1():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert CompilerFlags() == CompilerFlags(None) == CompilerFlags(0)

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
