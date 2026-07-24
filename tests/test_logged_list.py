# pyflyby/test_logged_list.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

# Tests for pyflyby._py.LoggedList, the list proxy substituted for sys.argv.
# Since sys.argv is a plain list, LoggedList must expose the same public API and
# behave identically to a list for every operation, while additionally tracking
# which items were never accessed.

from __future__ import print_function

import pytest

from   pyflyby._py              import LoggedList


def test_logged_list_exposes_all_list_methods():
    # ``LoggedList`` stands in for ``sys.argv``, which is a plain ``list``, so
    # it must expose every public method a ``list`` does -- otherwise scripts
    # doing e.g. ``sys.argv.index("--flag")`` or ``sys.argv.count(x)`` break.
    list_methods = {name for name in dir(list) if not name.startswith("_")}
    missing = sorted(
        name for name in list_methods if not callable(getattr(LoggedList, name, None))
    )
    assert missing == [], "LoggedList is missing list methods: %s" % (missing,)


# ---------------------------------------------------------------------------
# LoggedList must behave like a plain ``list`` for every operation, since it
# is substituted for ``sys.argv``.  The bulk of these are the same shape --
# apply an operation to a real ``list`` and to a ``LoggedList`` seeded with the
# same data, then check the return value and resulting contents match -- so
# they are driven by a single parametrized harness.  The few tests that assert
# LoggedList's *access-tracking* behavior (which a plain list does not have)
# are kept separate below.
# ---------------------------------------------------------------------------

def _iadd(x):
    x += [3, 4]      # exercises real += (must return self, not None)
    return x


def _imul(x):
    x *= 3           # exercises real *= (must return self, not None)
    return x


# Each case is (seed_items, operation).  The operation is applied to both a
# list and a LoggedList; both its return value and the container's resulting
# contents must match.
_LIST_OPERATIONS = {
    "append":           ([1, 2, 3],          lambda x: x.append(4)),
    "clear":            ([1, 2, 3],          lambda x: x.clear()),
    "copy":             ([1, 2, 3],          lambda x: x.copy()),
    "count-present":    ([1, 2, 2, 3, 2],    lambda x: x.count(2)),
    "count-absent":     ([1, 2, 2, 3, 2],    lambda x: x.count(9)),
    "extend-list":      ([1, 2],             lambda x: x.extend([3, 4])),
    "extend-iter":      ([1, 2],             lambda x: x.extend(iter([3, 4]))),
    "index":            (["a", "b", "c", "b"], lambda x: x.index("b")),
    "index-start":      (["a", "b", "c", "b"], lambda x: x.index("b", 2)),
    "index-start-stop": (["a", "b", "c", "b"], lambda x: x.index("b", 1, 4)),
    "insert":           ([1, 2, 3],          lambda x: x.insert(1, 99)),
    "pop-default":      ([1, 2, 3],          lambda x: x.pop()),
    "pop-index":        ([1, 2, 3],          lambda x: x.pop(0)),
    "remove":           ([1, 2, 3, 2],       lambda x: x.remove(2)),
    "reverse":          ([1, 2, 3],          lambda x: x.reverse()),
    "sort":             ([3, 1, 2],          lambda x: x.sort()),
    "sort-key-reverse": (["bbb", "a", "cc"], lambda x: x.sort(key=len, reverse=True)),
    "getitem":          ([1, 2, 3, 4],       lambda x: x[2]),
    "getitem-negative": ([1, 2, 3, 4],       lambda x: x[-1]),
    "getitem-slice":    ([1, 2, 3, 4],       lambda x: x[1:3]),
    "getitem-slice-step": ([1, 2, 3, 4],     lambda x: x[::-1]),
    "setitem":          ([1, 2, 3],          lambda x: x.__setitem__(1, 99)),
    "setitem-slice":    ([1, 2, 3, 4],       lambda x: x.__setitem__(slice(1, 3), [8, 9, 10])),
    "delitem":          ([1, 2, 3],          lambda x: x.__delitem__(1)),
    "delitem-slice":    ([1, 2, 3, 4],       lambda x: x.__delitem__(slice(1, 3))),
    "len":              ([1, 2, 3],          lambda x: len(x)),
    "iter":             ([1, 2, 3],          lambda x: list(iter(x))),
    "reversed":         ([1, 2, 3],          lambda x: list(reversed(x))),
    "contains-present": ([1, 2, 3],          lambda x: 2 in x),
    "contains-absent":  ([1, 2, 3],          lambda x: 9 in x),
    "add":              ([1, 2],             lambda x: x + [3, 4]),
    "mul":              ([1, 2],             lambda x: x * 3),
    "rmul":             ([1, 2],             lambda x: 3 * x),
    "iadd":             ([1, 2],             _iadd),
    "imul":             ([1, 2],             _imul),
    "repr":             ([1, 2, 3],          lambda x: repr(x)),
    "str":              ([1, 2, 3],          lambda x: str(x)),
}


@pytest.mark.parametrize(
    "seed, op",
    list(_LIST_OPERATIONS.values()),
    ids=list(_LIST_OPERATIONS.keys()),
)
def test_logged_list_operation_matches_list(seed, op):
    ref = list(seed)
    ll = LoggedList(seed)
    # Same return value (compared before/independently of any mutation)...
    assert op(ref) == op(ll)
    # ...and same resulting contents (compared without relying on __eq__).
    assert list(ll._items) == ref


@pytest.mark.parametrize(
    "op",
    [lambda x: x.index("z"), lambda x: x.remove("z")],
    ids=["index", "remove"],
)
def test_logged_list_operation_raises_like_list(op):
    with pytest.raises(ValueError):
        op(["a", "b"])
    with pytest.raises(ValueError):
        op(LoggedList(["a", "b"]))


def test_logged_list_copy_returns_plain_list():
    c = LoggedList([1, 2, 3]).copy()
    assert isinstance(c, list) and not isinstance(c, LoggedList)


@pytest.mark.parametrize("op, expected", [
    (lambda a, b: a == b,  True),
    (lambda a, b: a != b,  False),
    (lambda a, b: a < b,   False),
    (lambda a, b: a <= b,  True),
    (lambda a, b: a > b,   False),
    (lambda a, b: a >= b,  True),
], ids=["eq", "ne", "lt", "le", "gt", "ge"])
def test_logged_list_comparisons_match_list(op, expected):
    # LoggedList must compare against both plain lists and other LoggedLists
    # exactly as a list would.
    assert op(LoggedList([1, 2, 3]), [1, 2, 3]) == expected
    assert op(LoggedList([1, 2, 3]), LoggedList([1, 2, 3])) == expected
    assert op([1, 2, 3], [1, 2, 3]) == expected


def test_logged_list_unhashable_like_list():
    with pytest.raises(TypeError):
        hash([1, 2, 3])
    with pytest.raises(TypeError):
        hash(LoggedList([1, 2, 3]))


# --- access-tracking behavior specific to LoggedList (a list has none) ------

def test_logged_list_getitem_marks_accessed():
    ll = LoggedList(["a", "b", "c"])
    assert ll[1] == "b"
    assert ll.unaccessed == ["a", "c"]


def test_logged_list_slice_marks_accessed():
    ll = LoggedList(["a", "b", "c", "d"])
    assert ll[1:3] == ["b", "c"]
    assert ll.unaccessed == ["a", "d"]


def test_logged_list_iter_marks_all_accessed():
    ll = LoggedList(["a", "b", "c"])
    list(ll)
    assert ll.unaccessed == []


def test_logged_list_len_does_not_mark():
    ll = LoggedList(["a", "b"])
    assert len(ll) == 2
    assert ll.unaccessed == ["a", "b"]


def test_logged_list_repr_marks_all():
    ll = LoggedList(["a", "b"])
    repr(ll)
    assert ll.unaccessed == []


def test_logged_list_index_marks_accessed():
    ll = LoggedList(["--flag", "value", "other"])
    assert ll.index("value") == 1
    assert ll.unaccessed == ["--flag", "other"]


def test_logged_list_sort_preserves_access_tracking():
    ll = LoggedList([3, 1, 2])
    ll.sort()
    # Sorting does not count as accessing any element.
    assert ll.unaccessed == [1, 2, 3]


def test_logged_list_clear_marks_nothing_unaccessed():
    ll = LoggedList([1, 2, 3])
    ll.clear()
    assert ll.unaccessed == []


def test_logged_list_copy_marks_all_accessed():
    # A copy reads every element, like ``sys.argv[:]``.
    ll = LoggedList([1, 2, 3])
    ll.copy()
    assert ll.unaccessed == []
