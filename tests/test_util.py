# pyflyby/test_util.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   pyflyby._util            import (longest_common_prefix, partition,
                                        prefixes, stable_unique)


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
