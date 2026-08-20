# pyflyby/test_util.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import pytest

from pyflyby._util import (
    _parse_ignore_undefined_pragmas,
    _pragma_args,
    longest_common_prefix,
    partition,
    prefixes,
    stable_unique,
)


def test_stable_unique_1():
    assert stable_unique([1,4,6,4,6,5,7]) == [1, 4, 6, 5, 7]


def test_longest_common_prefix_1():
    assert longest_common_prefix("abcde", "abcxy") == 'abc'


def test_prefixes_1():
    assert list(prefixes("abcd")) == ['a', 'ab', 'abc', 'abcd']


def test_partition_1():
    result = partition('12321233221', lambda c: int(c) % 2 == 0)
    expected = (['2', '2', '2', '2', '2'], ['1', '3', '1', '3', '3', '1'])
    assert result == expected


@pytest.mark.parametrize(
    ("line", "directive", "expected"),
    [
        ("import os  # tidy-imports: ignore-import", "ignore-import", []),
        # Spacing is strict: exactly one space after the '#' and after the ':'.
        ("import os  #tidy-imports:ignore-import", "ignore-import", None),
        ("import os  #  tidy-imports:  ignore-import", "ignore-import", None),
        # Arguments go in brackets; several directives can share one pragma.
        ("x  # tidy-imports: some[ a , b ]", "some", ["a", "b"]),
        ("x  # tidy-imports: one[a],two[b]", "two", ["b"]),
        ("x  # tidy-imports: one[a],two", "two", []),
        ("x  # tidy-imports: one[a],two[b]", "three", None),
        # Directives match in full, not as a prefix.
        ("import os  # tidy-imports: ignore-imports", "ignore-import", None),
        ("x = 1  # ordinary comment", "ignore-import", None),
    ],
)
def test_pragma_args(line, directive, expected):
    assert _pragma_args(line, directive) == expected


def test_parse_ignore_undefined_pragmas():
    lines = [
        "# tidy-imports: ignore-undefined[c, get_config]",
        "d.foo  # tidy-imports: ignore-undefined",
        "e.foo",
    ]
    assert _parse_ignore_undefined_pragmas(lines) == ({"c", "get_config"}, {2})
    assert _parse_ignore_undefined_pragmas([]) == (set(), set())
