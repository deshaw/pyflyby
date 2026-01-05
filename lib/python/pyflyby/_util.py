# pyflyby/_util.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



from   contextlib               import ExitStack, contextmanager
import inspect
import os
import sys
import types
from   types                    import MappingProxyType as DictProxyType

# There used to be a custom caching_attribute implementation
# this now uses functools's cached_property which is understood by
# various static analysis tools.
from   functools                import (cache as memoize,
                                        cached_property as cached_attribute)

__all__ = ["cached_attribute", "memoize"]


class WrappedAttributeError(Exception):
    pass


def stable_unique(items):
    """
    Return a copy of ``items`` without duplicates.  The order of other items is
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

    :rtype:
      ``type(items1)``
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


def indent(lines, prefix):
    r"""
      >>> indent('hello\nworld\n', '@@')
      '@@hello\n@@world\n'
    """
    return "".join("%s%s\n"%(prefix,line) for line in lines.splitlines(False))


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
    Context manager that temporarily prepends ``sys.path`` with ``path_additions``.
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
    Context manager that temporarily removes "." from ``sys.path``.
    """
    old_path = sys.path
    try:
        sys.path = [p for p in sys.path if p not in (".", "")]
        yield
    finally:
        sys.path[:] = old_path


class FunctionWithGlobals(object):
    """
    A callable that at runtime adds extra variables to the target function's
    global namespace.

    This is written as a class with a __call__ method.  We do so rather than
    using a metafunction, so that we can also implement __getattr__ to look
    through to the target.
    """

    def __init__(self, function, **variables):
        self.__function = function
        self.__variables = variables
        try:
            self.__original__ = variables["__original__"]
        except KeyError:
            pass

    def __call__(self, *args, **kwargs):
        function = self.__function
        variables = self.__variables
        undecorated = function
        while True:
            try:
                undecorated = undecorated.undecorated
            except AttributeError:
                break
        globals = undecorated.__globals__
        UNSET = object()
        old = {}
        for k in variables:
            old[k] = globals.get(k, UNSET)
        try:
            for k, v in variables.items():
                globals[k] = v
            return function(*args, **kwargs)
        finally:
            for k, v in old.items():
                if v is UNSET:
                    del globals[k]
                else:
                    globals[k] = v

    def __getattr__(self, k):
        return getattr(self.__original__, k)


    def __get__(self, inst, cls=None):
        if inst is None:
            return self
        return types.MethodType(self, inst)



class _WritableDictProxy(object):
    """
    Writable equivalent of cls.__dict__.
    """

    # We need to implement __getitem__ differently from __setitem__.  The
    # reason is because of an asymmetry in the mechanics of classes:
    #   - getattr(cls, k) does NOT in general do what we want because it
    #     returns unbound methods.  It's actually equivalent to
    #     cls.__dict__[k].__get__(cls).
    #   - setattr(cls, k, v) does do what we want.
    #   - cls.__dict__[k] does do what we want.
    #   - cls.__dict__[k] = v does not work, because dictproxy is read-only.

    def __init__(self, cls):
        self._cls = cls

    def __getitem__(self, k):
        return self._cls.__dict__[k]

    def get(self, k, default=None):
        return self._cls.__dict__.get(k, default)

    def __setitem__(self, k, v):
        setattr(self._cls, k, v)

    def __delitem__(self, k):
        delattr(self._cls, k)


_UNSET = object()

class Aspect(object):
    """
    Monkey-patch a target method (joinpoint) with "around" advice.

    The advice can call "__original__(...)".  At run time, a global named
    "__original__" will magically be available to the wrapped function.
    This refers to the original function.

    Suppose someone else wrote Foo.bar()::

      >>> class Foo(object):
      ...     def __init__(self, x):
      ...         self.x = x
      ...     def bar(self, y):
      ...         return "bar(self.x=%s,y=%s)" % (self.x,y)

      >>> foo = Foo(42)

    To monkey patch ``foo.bar``, decorate the wrapper with ``"@advise(foo.bar)"``::

      >>> @advise(foo.bar)
      ... def addthousand(y):
      ...     return "advised foo.bar(y=%s): %s" % (y, __original__(y+1000))

      >>> foo.bar(100)
      'advised foo.bar(y=100): bar(self.x=42,y=1100)'

    You can uninstall the advice and get the original behavior back::

      >>> addthousand.unadvise()

      >>> foo.bar(100)
      'bar(self.x=42,y=100)'

    :see:
      http://en.wikipedia.org/wiki/Aspect-oriented_programming
    """

    _wrapper = None

    def __init__(self, joinpoint):
        spec = joinpoint
        while hasattr(joinpoint, "__joinpoint__"):
            joinpoint = joinpoint.__joinpoint__
        self._joinpoint = joinpoint
        if (isinstance(joinpoint, (types.FunctionType, type))
            and not (joinpoint.__name__ != joinpoint.__qualname__)):
            self._qname = "%s.%s" % (
                joinpoint.__module__,
                joinpoint.__name__)
            self._container = sys.modules[joinpoint.__module__].__dict__
            self._name      = joinpoint.__name__
            self._original  = spec
            assert spec == self._container[self._name], joinpoint
        elif isinstance(joinpoint, types.MethodType) or (isinstance(joinpoint,
            types.FunctionType) and joinpoint.__name__ !=
            joinpoint.__qualname__) or isinstance(joinpoint, property):
            if isinstance(joinpoint, property):
                joinpoint = joinpoint.fget
                self._wrapper = property
            self._qname = '%s.%s' % (joinpoint.__module__,
                                     joinpoint.__qualname__)
            self._name      = joinpoint.__name__
            if getattr(joinpoint, '__self__', None) is None:
                container_obj   = getattr(inspect.getmodule(joinpoint),
                   joinpoint.__qualname__.split('.<locals>', 1)[0].rsplit('.', 1)[0])

                self._container = _WritableDictProxy(container_obj)
                self._original  = spec
            else:
                # Instance method.
                container_obj   = joinpoint.__self__
                self._container = container_obj.__dict__
                self._original  = spec
            assert spec == getattr(container_obj, self._name), (container_obj, self._qname)
            assert self._original == self._container.get(self._name, self._original)
        elif isinstance(joinpoint, tuple) and len(joinpoint) == 2:
            container, name = joinpoint
            if isinstance(container, dict):
                self._original  = container[name]
                self._container = container
                self._qname = name
            elif name in container.__dict__.get('_trait_values', ()):
                # traitlet stuff from IPython
                self._container = container._trait_values
                self._original = self._container[name]
                self._qname = name
            elif isinstance(container.__dict__, DictProxyType):
                original = getattr(container, name)
                if hasattr(original, "__func__"):
                    # TODO: generalize this to work for all cases, not just classmethod
                    original = original.__func__
                    self._wrapper = classmethod
                self._original = original
                self._container = _WritableDictProxy(container)
                self._qname = "%s.%s.%s" % (
                    container.__module__, container.__name__, name)
            else:
                # Keep track of the original.  We use getattr on the
                # container, instead of getitem on container.__dict__, so that
                # it works even if it's a class dict proxy that inherits the
                # value from a super class.
                self._original = getattr(container, name)
                self._container = container.__dict__
                self._qname = "%s.%s.%s" % (
                    container.__class__.__module__,
                    container.__class__.__name__,
                    name)
            self._name      = name
        # TODO: unbound method
        else:
            raise TypeError("JoinPoint: unexpected type %s"
                            % (type(joinpoint).__name__,))
        self._wrapped = None

    def advise(self, hook, once=False):
        from pyflyby._log import logger
        self._previous = self._container.get(self._name, _UNSET)
        if once and getattr(self._previous, "__aspect__", None) :
            # TODO: check that it's the same hook - at least check the name.
            logger.debug("already advised %s", self._qname)
            return None
        logger.debug("advising %s", self._qname)
        assert self._previous is _UNSET or self._previous == self._original
        assert self._wrapped is None
        # Create the wrapped function.
        wrapped = FunctionWithGlobals(hook, __original__=self._original)
        wrapped.__joinpoint__ = self._joinpoint
        wrapped.__original__ = self._original
        wrapped.__name__ = "%s__advised__%s" % (self._name, hook.__name__)
        wrapped.__doc__ = "%s.\n\nAdvice %s:\n%s" % (
            self._original.__doc__, hook.__name__, hook.__doc__)
        wrapped.__aspect__ = self
        if self._wrapper is not None:
            wrapped = self._wrapper(wrapped)
        self._wrapped = wrapped
        # Install the wrapped function!
        self._container[self._name] = wrapped
        return self

    def unadvise(self):
        if self._wrapped is None:
            return
        cur = self._container.get(self._name, _UNSET)
        if cur is self._wrapped:
            from pyflyby._log import logger
            logger.debug("unadvising %s", self._qname)
            if self._previous is _UNSET:
                del self._container[self._name]
            else:
                self._container[self._name] = self._previous
        elif cur == self._previous:
            pass
        else:
            from pyflyby._log import logger
            logger.debug("%s seems modified; not unadvising it", self._name)
        self._wrapped = None


def advise(joinpoint):
    """
    Advise ``joinpoint``.

    See `Aspect`.
    """
    aspect = Aspect(joinpoint)
    return aspect.advise


@contextmanager
def AdviceCtx(joinpoint, hook):
    aspect = Aspect(joinpoint)
    advice = aspect.advise(hook)
    try:
        yield
    finally:
        advice.unadvise()

# For Python 2/3 compatibility. cmp isn't included with six.
def cmp(a, b):
    return (a > b) - (a < b)


# Create a context manager with an arbitrary number of contexts.
@contextmanager
def nested(*mgrs):
    with ExitStack() as stack:
        ctxes = [stack.enter_context(mgr) for mgr in mgrs]
        yield ctxes
