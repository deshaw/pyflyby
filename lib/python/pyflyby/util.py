
from __future__ import absolute_import, division, with_statement

import keyword
import re


def memoize(function):
    cache = {}
    def wrapped_fn(*args, **kwargs):
        cache_key = (args, tuple(sorted(kwargs.items())))
        try:
            return cache[cache_key]
        except KeyError:
            result = function(*args, **kwargs)
            cache[cache_key] = result
            return result
    return wrapped_fn


class cached_attribute(object):
    '''Computes attribute value and caches it in instance.

    Example:
        class MyClass(object):
            @cached_attribute
            def myMethod(self):
                # ...
    Use "del inst.myMethod" to clear cache.'''
    # http://code.activestate.com/recipes/276643/

    def __init__(self, method, name=None):
        self.method = method
        self.name = name or method.__name__

    def __get__(self, inst, cls):
        if inst is None:
            return self
        result = self.method(inst)
        setattr(inst, self.name, result)
        return result


def stable_unique(items):
    """
    Return a copy of C{items} without duplicates.  The order of other items is
    unchanged.

      >>> stable_unique([1,4,6,4,6,5,7])
      [1, 4, 6, 5, 7]
    """
    result = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def longest_common_prefix(items1, items2):
    """
    Return the longest common prefix.

      >>> longest_common_prefix("abcde", "abcxy")
      'abc'

    @rtype:
      C{type(items1)}
    """
    n = 0
    for x1, x2 in zip(items1, items2):
        if x1 != x2:
            break
        n += 1
    return items1[:n]


def prefixes(parts):
    """
      >>> list(prefixes("abcd"))
      ['a', 'ab', 'abc', 'abcd']

    """
    for i in range(1, len(parts)+1):
        yield parts[:i]


def dotted_prefixes(dotted_name, reverse=False):
    """
    Return the prefixes of a dotted name.

      >>> dotted_prefixes("aa.bb.cc")
      ['aa', 'aa.bb', 'aa.bb.cc']

      >>> dotted_prefixes("aa.bb.cc", reverse=True)
      ['aa.bb.cc', 'aa.bb', 'aa']

    @type dotted_name:
      C{str}
    @param reverse:
      If False (default), return shortest to longest.  If True, return longest
      to shortest.
    @rtype:
      C{list} of C{str}
    """
    name_parts = dotted_name.split(".")
    if reverse:
        idxes = range(len(name_parts), 0, -1)
    else:
        idxes = range(1, len(name_parts)+1)
    result = ['.'.join(name_parts[:i]) for i in idxes]
    return result


def partition(iterable, predicate):
    """
      >>> partition('12321233221', lambda c: int(c) % 2 == 0)
      (['2', '2', '2', '2', '2'], ['1', '3', '1', '3', '3', '1'])

    """
    falses = []
    trues = []
    for item in iterable:
        if predicate(item):
            trues.append(item)
        else:
            falses.append(item)
    return trues, falses


_name_re               = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*$")
_dotted_name_re        = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*([.][a-zA-Z_][a-zA-Z0-9_]*)*$")
_dotted_name_prefix_re = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*([.][a-zA-Z_][a-zA-Z0-9_]*)*[.]?$")

def is_identifier(s, dotted=False, prefix=False):
    """
    Return whether C{s} is a valid Python identifier name.

      >>> is_identifier("foo")
      True

      >>> is_identifier("foo+bar")
      False

      >>> is_identifier("from")
      False

    By default, we check whether C{s} is a single valid identifier, meaning
    dots are not allowed.  If C{dotted=True}, then we check each dotted
    component:

      >>> is_identifier("foo.bar")
      False

      >>> is_identifier("foo.bar", dotted=True)
      True

      >>> is_identifier("foo..bar", dotted=True)
      False

      >>> is_identifier("foo.from", dotted=True)
      False

    By default, the string must comprise a valid identifier.  If
    C{prefix=True}, then allow strings that are prefixes of valid identifiers.
    Prefix=False excludes the empty string, strings with a trailing dot, and
    strings with a trailing keyword component, but prefix=True does not
    exclude these.

      >>> is_identifier("foo.bar.", dotted=True)
      False

      >>> is_identifier("foo.bar.", dotted=True, prefix=True)
      True

      >>> is_identifier("foo.or", dotted=True)
      False

      >>> is_identifier("foo.or", dotted=True, prefix=True)
      True

    @type s:
      C{str}
    @param dotted:
      If C{False} (default), then the input must be a single name such as
      "foo".  If C{True}, then the input can be a single name or a dotted name
      such as "foo.bar.baz".
    @param prefix:
      If C{False} (Default), then the input must be a valid identifier.  If
      C{True}, then the input can be a valid identifier or the prefix of a
      valid identifier.
    @rtype:
      C{bool}
    """
    if not isinstance(s, basestring):
        raise TypeError("is_identifier(): expected a string; got a %s"
                        % (type(s).__name__,))
    if prefix:
        if not s:
            return True
        if dotted:
            return bool(
                _dotted_name_prefix_re.match(s) and
                not any(keyword.iskeyword(w) for w in s.split(".")[:-1]))
        else:
            return bool(_name_re.match(s))
    else:
        if dotted:
            # Use a regular expression that works for dotted names.  (As an
            # alternate implementation, one could imagine calling
            # all(is_identifier(w) for w in s.split(".")).  We don't do that
            # because s could be a long text string.)
            return bool(
                _dotted_name_re.match(s) and
                not any(keyword.iskeyword(w) for w in s.split(".")))
        else:
            return bool(_name_re.match(s) and not keyword.iskeyword(s))


Inf = float('Inf')
