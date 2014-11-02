# pyflyby/_util.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

from   contextlib               import contextmanager
import os
import sys


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


class WrappedAttributeError(Exception):
    pass


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
        try:
            result = self.method(inst)
        except AttributeError as e:
            raise WrappedAttributeError(str(e)), None, sys.exc_info()[2]
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


Inf = float('Inf')


@contextmanager
def NullCtx():
    """
    Context manager that does nothing.
    """
    yield


@contextmanager
def ImportPathCtx(path_additions):
    """
    Context manager that temporarily prepends C{sys.path} with C{path_additions}.
    """
    if not isinstance(path_additions, (tuple, list)):
        path_additions = [path_additions]
    old_path = sys.path[:]
    sys.path[0:0] = path_additions
    try:
        yield
    finally:
        sys.path[:] = old_path


@contextmanager
def CwdCtx(path):
    """
    Context manager that temporarily enters a new working directory.
    """
    old_cwd = os.getcwd()
    os.chdir(str(path))
    try:
        yield
    finally:
        os.chdir(old_cwd)


@contextmanager
def EnvVarCtx(**kwargs):
    """
    Context manager that temporarily modifies os.environ.
    """
    unset = object()
    old = {}
    try:
        for k, v in kwargs.items():
            old[k] = os.environ.get(k, unset)
            os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is unset:
                del os.environ[k]
            else:
                os.environ[k] = v


@contextmanager
def ExcludeImplicitCwdFromPathCtx():
    """
    Context manager that temporarily removes "." from C{sys.path}.
    """
    old_path = sys.path
    try:
        sys.path = [p for p in sys.path if p not in (".", "")]
        yield
    finally:
        sys.path[:] = old_path
