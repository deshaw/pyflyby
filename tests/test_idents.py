# -*- coding: utf-8 -*-
# pyflyby/test_idents.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/




from   pyflyby._idents          import (brace_identifiers, dotted_prefixes,
                                        is_identifier)


def test_dotted_prefixes_1():
    assert dotted_prefixes("aa.bb.cc") == ['aa', 'aa.bb', 'aa.bb.cc']


def test_dotted_prefixes_reverse_1():
    result = dotted_prefixes("aa.bb.cc", reverse=True)
    assert result == ['aa.bb.cc', 'aa.bb', 'aa']


def test_dotted_prefixes_dot_1():
    assert dotted_prefixes(".aa.bb") == ['.', '.aa', '.aa.bb']


def test_dotted_prefixes_dot_reverse_1():
    assert dotted_prefixes(".aa.bb", reverse=True) == ['.aa.bb', '.aa', '.']


def test_is_identifier_basic_1():
    assert     is_identifier("foo")


def test_is_identifier_bad_char_1():
    assert not is_identifier("foo+bar")


def test_is_identifier_keyword_1():
    assert not is_identifier("from")


def test_is_identifier_print_1():
    assert     is_identifier("print")


def test_is_identifier_unwanted_dot_1():
    assert not is_identifier("foo.bar")


def test_is_identifier_dotted_1():
    assert     is_identifier("foo.bar", dotted=True)


def test_is_identifier_bad_dotted_1():
    assert not is_identifier("foo..bar", dotted=True)


def test_is_identifier_dotted_keyword_1():
    assert not is_identifier("foo.from", dotted=True)


def test_is_identifier_dotted_print_1():
    assert     is_identifier("foo.print.bar", dotted=True)


def test_is_identifier_prefix_trailing_dot_1():
    assert not is_identifier("foo.bar.", dotted=True             )
    assert     is_identifier("foo.bar.", dotted=True, prefix=True)


def test_is_identifier_prefix_keyword_1():
    assert not is_identifier("foo.or", dotted=True             )
    assert     is_identifier("foo.or", dotted=True, prefix=True)


def test_is_identifier_empty_1():
    assert not is_identifier("",                         )
    assert not is_identifier("", dotted=True             )
    assert     is_identifier("",              prefix=True)
    assert     is_identifier("", dotted=True, prefix=True)


def test_brace_identifiers_1():
    result = list(brace_identifiers("{salutation}, {your_name}."))
    expected = ['salutation', 'your_name']
    assert result == expected


def test_is_identifier_unicode():
    assert is_identifier('א')
    assert not is_identifier('א.')
    assert not is_identifier('א.א')
    assert not is_identifier('א.', prefix=True)
    assert is_identifier('א.', dotted=True, prefix=True)
    assert is_identifier('א.א', dotted=True)
