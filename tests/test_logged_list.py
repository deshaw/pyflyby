# pyflyby/test_logged_list.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

# Tests for pyflyby._py.LoggedList, the list substituted for sys.argv.  It must
# behave exactly like a list, while additionally tracking which items were
# never accessed.
#
# Only the methods LoggedList overrides are tested; anything it inherits is
# CPython's list and needs no coverage here.

import copy
import inspect
import operator

import pytest

from   pyflyby._py              import LoggedList


def _raw(ll):
    # Contents without going through the overrides, so that inspecting a
    # LoggedList in a test is not itself an access.
    return list.copy(ll)


def _check_aligned(ll):
    items = _raw(ll)
    assert len(ll._unaccessed) == len(
        items
    ), "out of sync: %d items, %d tracking slots" % (len(items), len(ll._unaccessed))
    for i, (item, tracked) in enumerate(zip(items, ll._unaccessed)):
        assert tracked is LoggedList._ACCESSED or tracked == item, (
            "misaligned at %d: item %r, tracking %r" % (i, item, tracked))


# List behavior deliberately left alone, because it neither mutates the list
# nor needs to mark anything.
_TRACKING_NEUTRAL = {
    "count",                                        # reports a tally only
    "__len__",                                      # a count, not a read
    "__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__",
    "__hash__",                                     # None, as on list
    "__class_getitem__",                            # types, not items
    "__init_subclass__", "__new__", "__sizeof__", "__subclasshook__",
    "__reduce__", "__reduce_ex__", "__getstate__",  # pickling unsupported
}


def test_inherits_only_tracking_neutral_methods():
    # Anything not overridden operates on the underlying storage directly,
    # silently skipping the tracking.  This is the tripwire for a method (e.g.
    # one added by a future Python) slipping through untracked.
    # Names taken from object unchanged (__dir__, __setattr__, ...) are not
    # list behavior at all, so they are not in scope.
    inherited = sorted(name for name in dir(list)
                       if getattr(list, name, None) is not getattr(object, name, None)
                       and name not in vars(LoggedList)
                       and name not in _TRACKING_NEUTRAL)
    assert inherited == [], (
        "inherited rather than overridden, so untracked: %s" % (inherited,))


def test_method_signatures_match_list():
    mismatched = {}
    for name in sorted(n for n in dir(list)
                       if not n.startswith("_") and n in vars(LoggedList)):
        actual = inspect.signature(getattr(LoggedList, name))
        expected = inspect.signature(getattr(list, name))
        if actual != expected:
            mismatched[name] = "%s != %s" % (actual, expected)
    assert mismatched == {}


# ---------------------------------------------------------------------------
# Each override must return what list returns and leave the same contents,
# with the tracking still aligned.
# ---------------------------------------------------------------------------

_OPERATIONS = {
    "append":             ([1, 2, 3],       lambda x: x.append(4)),
    "clear":              ([1, 2, 3],       lambda x: x.clear()),
    "copy":               ([1, 2, 3],       lambda x: x.copy()),
    "extend":             ([1, 2],          lambda x: x.extend([3, 4])),
    "extend-iter":        ([1, 2],          lambda x: x.extend(iter([3, 4]))),
    "index":              (["a", "b", "a"], lambda x: x.index("b")),
    "index-start-stop":   (["a", "b", "a"], lambda x: x.index("a", 1, 3)),
    "insert":             ([1, 2, 3],       lambda x: x.insert(1, 99)),
    "pop":                ([1, 2, 3],       lambda x: x.pop()),
    "pop-index":          ([1, 2, 3],       lambda x: x.pop(0)),
    "remove":             ([1, 2, 3, 2],    lambda x: x.remove(2)),
    "reverse":            ([1, 2, 3],       lambda x: x.reverse()),
    "sort":               ([3, 1, 2],       lambda x: x.sort()),
    "sort-key-reverse":   (["bbb", "a"],    lambda x: x.sort(key=len, reverse=True)),
    "getitem":            ([1, 2, 3],       lambda x: x[2]),
    "getitem-slice":      ([1, 2, 3, 4],    lambda x: x[1:3]),
    "setitem":            ([1, 2, 3],       lambda x: x.__setitem__(1, 99)),
    "setitem-slice-grow": ([1, 2, 3],       lambda x: x.__setitem__(slice(1, 2), iter("ab"))),
    "setitem-slice-step": ([1, 2, 3],       lambda x: x.__setitem__(slice(None, None, 2), iter("ab"))),
    "delitem":            ([1, 2, 3],       lambda x: x.__delitem__(1)),
    "delitem-slice":      ([1, 2, 3, 4],    lambda x: x.__delitem__(slice(1, 3))),
    "iter":               ([1, 2, 3],       lambda x: list(iter(x))),
    "reversed":           ([1, 2, 3],       lambda x: list(reversed(x))),
    "contains":           ([1, 2, 3],       lambda x: (2 in x, 9 in x)),
    "add":                ([1, 2],          lambda x: x + [3]),
    "mul":                ([1, 2],          lambda x: x * 3),
    "rmul":               ([1, 2],          lambda x: 3 * x),
    "iadd":               ([1, 2],          lambda x: operator.iadd(x, [3, 4])),
    "imul":               ([1, 2],          lambda x: operator.imul(x, 3)),
    "repr":               ([1, 2, 3],       lambda x: repr(x)),
    "self-extend":        ([1, 2],          lambda x: x.extend(x)),
}


@pytest.mark.parametrize("seed, op", list(_OPERATIONS.values()),
                         ids=list(_OPERATIONS.keys()))
def test_operation_matches_list(seed, op):
    ref, ll = list(seed), LoggedList(seed)
    assert op(ref) == op(ll)                 # same return value...
    assert _raw(ll) == ref                   # ...and same contents
    _check_aligned(ll)


_RAISING = {
    "remove-missing":    ([1, 2],    lambda x: x.remove(9),      ValueError),
    "pop-out-of-range":  ([1, 2],    lambda x: x.pop(5),         IndexError),
    "getitem-oob":       ([1, 2],    lambda x: x[5],             IndexError),
    "setitem-ext-size":  ([1, 2, 3], lambda x: x.__setitem__(slice(None, None, 2), [1]),
                                                                 ValueError),
}


@pytest.mark.parametrize("seed, op, exc_type", list(_RAISING.values()),
                         ids=list(_RAISING.keys()))
def test_operation_raises_like_list(seed, op, exc_type):
    with pytest.raises(exc_type) as ref_exc:
        op(list(seed))
    ll = LoggedList(seed)
    with pytest.raises(exc_type) as exc:
        op(ll)
    assert str(exc.value) == str(ref_exc.value)
    _check_aligned(ll)

# ---------------------------------------------------------------------------
# Access tracking, which a plain list has none of.
# ---------------------------------------------------------------------------

# (seed, operation, the items expected to remain unaccessed afterwards)
_TRACKING = {
    "getitem":       (["a", "b", "c"], lambda x: x[1],                     ["a", "c"]),
    "getitem-slice": (["a", "b", "c"], lambda x: x[1:2],                   ["a", "c"]),
    "index":         (["a", "b", "c"], lambda x: x.index("b"),             ["a", "c"]),
    "contains":      (["a", "b", "c"], lambda x: "b" in x,                 ["a", "c"]),
    "contains-absent": (["a", "b"],    lambda x: "z" in x,                 ["a", "b"]),
    "setitem":       (["a", "b", "c"], lambda x: x.__setitem__(1, "x"),    ["a", "c"]),
    "setitem-slice": (["a", "b", "c"], lambda x: x.__setitem__(slice(1, 2), "xy"),
                                                                           ["a", "c"]),
    "iter":          (["a", "b"],      lambda x: list(x),                  []),
    "repr":          (["a", "b"],      lambda x: repr(x),                  []),
    "copy":          (["a", "b"],      lambda x: x.copy(),                 []),
    "add":           (["a", "b"],      lambda x: x + ["z"],                []),
    "mul":           (["a", "b"],      lambda x: x * 2,                    []),
    "len":           (["a", "b"],      lambda x: len(x),                   ["a", "b"]),
    "sort":          ([3, 1, 2],       lambda x: x.sort(),                 [1, 2, 3]),
    "append":        (["a"],           lambda x: x.append("b"),            ["a"]),
}


@pytest.mark.parametrize("seed, op, expected", list(_TRACKING.values()),
                         ids=list(_TRACKING.keys()))
def test_operation_marks_expected_items_accessed(seed, op, expected):
    ll = LoggedList(seed)
    op(ll)
    assert ll.unaccessed == expected
    _check_aligned(ll)


@pytest.mark.parametrize("clone", [copy.copy, copy.deepcopy], ids=["copy", "deepcopy"])
def test_copy_preserves_tracking(clone):
    ll = LoggedList(["a", "b", "c"])
    ll[1]
    c = clone(ll)
    assert isinstance(c, LoggedList)
    assert _raw(c) == ["a", "b", "c"]
    assert c.unaccessed == ["a", "c"]
    c[0]
    assert (c.unaccessed, ll.unaccessed) == (["c"], ["a", "c"])
