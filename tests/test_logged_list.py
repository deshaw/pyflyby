# pyflyby/test_logged_list.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

# Tests for pyflyby._py.LoggedList, the list proxy substituted for sys.argv.
# Since sys.argv is a plain list, LoggedList must expose the same public API and
# behave identically to a list for every operation, while additionally tracking
# which items were never accessed.

from __future__ import print_function

import operator

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
    "setitem-slice-iterator": ([1, 2, 3],    lambda x: x.__setitem__(slice(1, 2), iter(["x"]))),
    "setitem-slice-iterator-grow": ([1, 2, 3], lambda x: x.__setitem__(slice(1, 2), iter(["a", "b", "c"]))),
    "setitem-slice-iterator-empty": ([1, 2, 3], lambda x: x.__setitem__(slice(1, 2), iter([]))),
    "setitem-slice-step-iterator": ([1, 2, 3], lambda x: x.__setitem__(slice(None, None, 2), iter(["a", "b"]))),
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
    (operator.eq, True),
    (operator.ne, False),
    (operator.lt, False),
    (operator.le, True),
    (operator.gt, False),
    (operator.ge, True),
], ids=["eq", "ne", "lt", "le", "gt", "ge"])
def test_logged_list_comparisons_match_list(op, expected):
    # LoggedList must compare against both plain lists and other LoggedLists
    # exactly as a list would.
    assert op(LoggedList([1, 2, 3]), [1, 2, 3]) == expected
    assert op(LoggedList([1, 2, 3]), LoggedList([1, 2, 3])) == expected
    assert op([1, 2, 3], [1, 2, 3]) == expected


_COMPARISON_OPS = [
    operator.eq, operator.ne, operator.lt,
    operator.le, operator.gt, operator.ge,
]


@pytest.mark.parametrize("left, right", [
    ([1, 2, 3], [1, 2, 4]),      # differs in the last element
    ([1, 2, 4], [1, 2, 3]),      # ...and the other way around
    ([1, 2],    [1, 2, 3]),      # proper prefix (shorter sorts first)
    ([1, 2, 3], [1, 2]),         # ...and the other way around
    ([2],       [1, 2, 3]),      # first element decides, regardless of length
    ([],        [1]),            # empty vs non-empty
    (["a", "b"], ["a", "c"]),    # non-numeric elements
], ids=["last-lt", "last-gt", "prefix", "extends", "first-wins", "empty", "str"])
@pytest.mark.parametrize("op", _COMPARISON_OPS,
                         ids=[op.__name__ for op in _COMPARISON_OPS])
def test_logged_list_unequal_comparisons_match_list(op, left, right):
    # Comparisons between *unequal* operands: these exercise the orderings
    # ``total_ordering`` derives from __eq__/__lt__, which comparing equal
    # lists barely touches.  The expected result is whatever plain lists do.
    expected = op(left, right)
    assert op(LoggedList(left), right) == expected
    assert op(LoggedList(left), LoggedList(right)) == expected
    # ...including with a plain list on the left, which goes through the
    # reflected operator.
    assert op(left, LoggedList(right)) == expected


def test_logged_list_unequal_comparison_does_not_mark_accessed():
    # Comparing does not count as accessing the individual arguments.
    ll = LoggedList(["a", "b"])
    assert (ll != ["a", "c"]) is True
    assert ll.unaccessed == ["a", "b"]


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


@pytest.mark.parametrize("value, expected", [
    (iter(["x"]),           [1, "x", 3]),
    (iter(["a", "b", "c"]), [1, "a", "b", "c", 3]),
    (iter([]),              [1, 3]),
], ids=["same-size", "grow", "shrink"])
def test_logged_list_setitem_slice_accepts_iterator(value, expected):
    # A slice assignment accepts any iterable, and may change the length of the
    # list.  The length therefore has to come from the value (which must be
    # materialized, since the assignment itself would consume the iterator),
    # not from the slice.
    ll = LoggedList([1, 2, 3])
    ll[1:2] = value
    assert list(ll._items) == expected
    # The access-tracking bookkeeping must stay in sync with the items.
    assert len(ll._unaccessed) == len(ll._items)


def test_logged_list_setitem_extended_slice_iterator_size_mismatch():
    # An extended slice assignment of the wrong size raises, as for a list, and
    # must leave both the items and the tracking state untouched.
    ll = LoggedList([1, 2, 3])
    with pytest.raises(ValueError):
        ll[::2] = iter(["a"])
    assert list(ll._items) == [1, 2, 3]
    assert len(ll._unaccessed) == 3


def test_logged_list_setitem_slice_marks_assigned_accessed():
    ll = LoggedList(["a", "b", "c"])
    ll[1:2] = iter(["x", "y"])
    # The freshly-assigned positions count as accessed; the rest do not.
    assert ll.unaccessed == ["a", "c"]


def test_logged_list_setitem_marks_assigned_accessed():
    # A single-index assignment marks that position accessed, consistently with
    # slice assignment: neither the replaced value nor the newly-assigned one is
    # an unused argument.
    ll = LoggedList(["a", "b", "c"])
    ll[1] = "x"
    assert ll.unaccessed == ["a", "c"]


def test_logged_list_setitem_does_not_mark_others_accessed():
    ll = LoggedList(["a", "b", "c"])
    ll[0] = "x"
    ll[-1] = "z"
    assert list(ll._items) == ["x", "b", "z"]
    assert ll.unaccessed == ["b"]


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
