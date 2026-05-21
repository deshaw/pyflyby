# -*- coding: utf-8 -*-
# pyflyby/test_idents.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/




import pytest

from   pyflyby._idents          import (BadDottedIdentifierError,
                                        DottedIdentifier, brace_identifiers,
                                        dotted_prefixes, is_identifier)


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


def test_is_identifier_type_error():
    with pytest.raises(TypeError):
        is_identifier(42)


def test_brace_identifiers_no_match():
    assert list(brace_identifiers("no braces here")) == []


def test_brace_identifiers_bytes():
    result = list(brace_identifiers(b"{hello}, world"))
    assert result == ['hello']


def test_brace_identifiers_bad_token():
    # Tokens with non-identifier chars should not match
    assert list(brace_identifiers("{1bad}")) == []
    assert list(brace_identifiers("{foo-bar}")) == []


def test_dotted_identifier_from_string():
    d = DottedIdentifier("foo.bar.baz")
    assert d.name == "foo.bar.baz"
    assert d.parts == ("foo", "bar", "baz")


def test_dotted_identifier_from_tuple():
    d = DottedIdentifier(("foo", "bar"))
    assert d.name == "foo.bar"


def test_dotted_identifier_from_list():
    d = DottedIdentifier(["foo", "bar"])
    assert d.name == "foo.bar"


def test_dotted_identifier_from_self():
    d = DottedIdentifier("foo.bar")
    d2 = DottedIdentifier(d)
    assert d is d2


def test_dotted_identifier_bad_type():
    with pytest.raises(TypeError):
        DottedIdentifier(42)


def test_dotted_identifier_invalid():
    with pytest.raises(BadDottedIdentifierError):
        DottedIdentifier("foo+bar")


def test_dotted_identifier_invalid_long():
    # Long invalid names get a generic message (no repr)
    with pytest.raises(BadDottedIdentifierError):
        DottedIdentifier("foo+bar+baz+quux+something_really_long")


def test_dotted_identifier_parent():
    d = DottedIdentifier("foo.bar.baz")
    assert str(d.parent) == "foo.bar"
    assert str(d.parent.parent) == "foo"
    assert d.parent.parent.parent is None


def test_dotted_identifier_prefixes():
    d = DottedIdentifier("aa.bb.cc")
    pre = d.prefixes
    assert [str(x) for x in pre] == ["aa", "aa.bb", "aa.bb.cc"]
    assert all(isinstance(x, DottedIdentifier) for x in pre)


def test_dotted_identifier_startswith():
    d = DottedIdentifier("foo.bar.baz")
    assert d.startswith("foo")
    assert d.startswith("foo.bar")
    assert d.startswith("foo.bar.baz")
    assert not d.startswith("foo.barx")
    assert not d.startswith("bar")


def test_dotted_identifier_getitem():
    d = DottedIdentifier("foo.bar.baz")
    assert str(d[0]) == "foo"
    assert str(d[1]) == "bar"
    assert str(d[-1]) == "baz"


def test_dotted_identifier_len():
    assert len(DottedIdentifier("foo")) == 1
    assert len(DottedIdentifier("foo.bar")) == 2
    assert len(DottedIdentifier("foo.bar.baz")) == 3


def test_dotted_identifier_iter():
    parts = list(DottedIdentifier("foo.bar.baz"))
    assert [str(p) for p in parts] == ["foo", "bar", "baz"]


def test_dotted_identifier_add():
    d = DottedIdentifier("foo.bar")
    d2 = d + "baz"
    assert str(d2) == "foo.bar.baz"


def test_dotted_identifier_str_and_repr():
    d = DottedIdentifier("foo.bar")
    assert str(d) == "foo.bar"
    assert repr(d) == "DottedIdentifier('foo.bar')"


def test_dotted_identifier_hash_eq():
    d1 = DottedIdentifier("foo.bar")
    d2 = DottedIdentifier("foo.bar")
    d3 = DottedIdentifier("foo.baz")
    assert d1 == d2
    assert hash(d1) == hash(d2)
    assert d1 != d3
    assert d1 == d1  # identity short-circuit


def test_dotted_identifier_eq_not_implemented():
    d = DottedIdentifier("foo")
    assert d.__eq__("foo") is NotImplemented
    assert d.__ne__("foo") is NotImplemented
    assert d.__lt__("foo") is NotImplemented


def test_dotted_identifier_ordering():
    a = DottedIdentifier("aa")
    b = DottedIdentifier("bb")
    assert a < b
    assert b > a
    assert a <= b
    assert b >= a
    assert sorted([b, a]) == [a, b]
