# pyflyby/test_util.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import os
import sys
import tempfile

import pytest

from   pyflyby._util            import (AdviceCtx, Aspect, CwdCtx, EnvVarCtx,
                                        ExcludeImplicitCwdFromPathCtx,
                                        ImportPathCtx, NullCtx, advise, cmp,
                                        indent, longest_common_prefix, nested,
                                        partition, prefixes, stable_unique)


def test_stable_unique_1():
    assert stable_unique([1,4,6,4,6,5,7]) == [1, 4, 6, 5, 7]


def test_stable_unique_empty():
    assert stable_unique([]) == []


def test_stable_unique_no_dupes():
    assert stable_unique([1, 2, 3]) == [1, 2, 3]


def test_stable_unique_all_same():
    assert stable_unique([5, 5, 5]) == [5]


def test_longest_common_prefix_1():
    assert longest_common_prefix("abcde", "abcxy") == 'abc'


def test_longest_common_prefix_empty():
    assert longest_common_prefix("", "abc") == ''
    assert longest_common_prefix("abc", "") == ''


def test_longest_common_prefix_identical():
    assert longest_common_prefix("abc", "abc") == 'abc'


def test_longest_common_prefix_no_overlap():
    assert longest_common_prefix("abc", "xyz") == ''


def test_longest_common_prefix_list():
    assert longest_common_prefix([1, 2, 3, 4], [1, 2, 9, 9]) == [1, 2]


def test_prefixes_1():
    assert list(prefixes("abcd")) == ['a', 'ab', 'abc', 'abcd']


def test_prefixes_empty():
    assert list(prefixes("")) == []


def test_prefixes_single():
    assert list(prefixes("a")) == ['a']


def test_partition_1():
    result = partition('12321233221', lambda c: int(c) % 2 == 0)
    expected = (['2', '2', '2', '2', '2'], ['1', '3', '1', '3', '3', '1'])
    assert result == expected


def test_partition_empty():
    trues, falses = partition([], lambda x: x)
    assert trues == []
    assert falses == []


def test_partition_all_true():
    trues, falses = partition([2, 4, 6], lambda x: x % 2 == 0)
    assert trues == [2, 4, 6]
    assert falses == []


def test_indent_basic():
    assert indent('hello\nworld\n', '@@') == '@@hello\n@@world\n'


def test_indent_empty():
    assert indent('', '>>') == ''


def test_indent_single_line_no_newline():
    assert indent('hello', '> ') == '> hello\n'


def test_indent_trailing_newline():
    assert indent('a\nb', '#') == '#a\n#b\n'


def test_nullctx():
    with NullCtx() as v:
        assert v is None


def test_import_path_ctx_single():
    sentinel = "/__pyflyby_test_sentinel_path__"
    assert sentinel not in sys.path
    with ImportPathCtx(sentinel):
        assert sys.path[0] == sentinel
    assert sentinel not in sys.path


def test_import_path_ctx_list():
    s1 = "/__pyflyby_test_sentinel_path1__"
    s2 = "/__pyflyby_test_sentinel_path2__"
    with ImportPathCtx([s1, s2]):
        assert s1 in sys.path
        assert s2 in sys.path
    assert s1 not in sys.path
    assert s2 not in sys.path


def test_cwd_ctx():
    old = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        real_tmp = os.path.realpath(tmp)
        with CwdCtx(tmp):
            assert os.path.realpath(os.getcwd()) == real_tmp
        assert os.getcwd() == old


def test_env_var_ctx_set_new():
    key = "__PYFLYBY_TEST_ENV_VAR_NEW__"
    assert key not in os.environ
    with EnvVarCtx(**{key: "hello"}):
        assert os.environ[key] == "hello"
    assert key not in os.environ


def test_env_var_ctx_override_existing():
    key = "__PYFLYBY_TEST_ENV_VAR_OLD__"
    os.environ[key] = "original"
    try:
        with EnvVarCtx(**{key: "new"}):
            assert os.environ[key] == "new"
        assert os.environ[key] == "original"
    finally:
        os.environ.pop(key, None)


def test_exclude_implicit_cwd():
    sys.path.insert(0, ".")
    sys.path.insert(0, "")
    try:
        with ExcludeImplicitCwdFromPathCtx():
            assert "." not in sys.path
            assert "" not in sys.path
        assert "." in sys.path
        assert "" in sys.path
    finally:
        while "." in sys.path:
            sys.path.remove(".")
        while "" in sys.path:
            sys.path.remove("")


def test_cmp():
    assert cmp(1, 2) == -1
    assert cmp(2, 1) == 1
    assert cmp(1, 1) == 0
    assert cmp("a", "b") == -1
    assert cmp("b", "a") == 1
    assert cmp("a", "a") == 0


def test_nested_context_managers():
    with nested(NullCtx(), NullCtx()) as ctxes:
        assert len(ctxes) == 2


def test_advise_function():
    # Advise a module-level function
    import pyflyby._util as u

    def _target(x):
        return x + 1
    u._target = _target

    @advise((u, '_target'))
    def wrapper(x):
        return __original__(x) * 10  # noqa: F821

    try:
        assert u._target(5) == 60
    finally:
        wrapper.unadvise()
    assert u._target(5) == 6
    del u._target


def test_advice_ctx():
    import pyflyby._util as u

    def _target2(x):
        return x
    u._target2 = _target2

    def hook(x):
        return __original__(x) + 100  # noqa: F821

    try:
        with AdviceCtx((u, '_target2'), hook):
            assert u._target2(5) == 105
        assert u._target2(5) == 5
    finally:
        del u._target2


def test_aspect_unsupported():
    with pytest.raises(TypeError):
        Aspect(42)
