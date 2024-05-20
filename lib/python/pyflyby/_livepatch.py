# pyflyby/_livepatch.py
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.

r"""
livepatch/xreload: Alternative to reload().

xreload performs a "live patch" of the modules/classes/functions/etc that have
already been loaded in memory.  It does so by executing the module in a
scratch namespace, and then patching classes, methods and functions in-place.
New objects are copied into the target namespace.

This addresses cases where one module imported functions from another
module.

For example, suppose m1.py contains::

  from m2 import foo
  def print_foo():
      return foo()

and m2.py contains::

  def foo():
      return 42

If you edit m2.py and modify ``foo``, then reload(m2) on its own would not do
what you want.  You would also need to reload(m1) after reload(m2).  This is
because the built-in reload affects the module being reloaded, but references
to the old module remain.  On the other hand, xreload() patches the existing
m2.foo, so that live references to it are updated.

In table form::

  Undesired effect:  reload(m2)
  Undesired effect:  reload(m1);  reload(m2)
  Desired effect:    reload(m2);  reload(m1)

  Desired effect:   xreload(m2)
  Desired effect:   xreload(m1); xreload(m2)
  Desired effect:   xreload(m2); xreload(m1)

Even with just two modules, we can see that xreload() is an improvement.  When
working with a large set of interdependent modules, it becomes infeasible to
know the precise sequence of reload() calls that would be necessary.
xreload() really shines in that case.

This implementation of xreload() was originally based the following
mailing-list post by Guido van Rossum:

    https://mail.python.org/pipermail/edu-sig/2007-February/007787.html

Customizing behavior
====================

If a class/function/module/etc has an attribute __livepatch__, then this
function is called *instead* of performing the regular livepatch mechanism.

The __livepatch__() function is called with the following arguments:

  - ``old``         : The object to be updated with contents of ``new``
  - ``new``         : The object whose contents to put into ``old``
  - ``do_livepatch``: A function that can be called to do the standard
                      livepatch, replacing the contents of ``old`` with ``new``.
                      If it's not possible to livepatch ``old``, it returns
                      ``new``.  The ``do_livepatch`` function takes no arguments.
                      Calling the ``do_livepatch`` function is roughly
                      equivalent to calling ``pyflyby.livepatch(old, new,
                      modname=modname, heed_hook=False)``.
  - ``modname``     : The module currently being updated.  Recursively called
                      updates should keep track of the module being updated to
                      avoid touching other modules.

These arguments are matched by *name* and are passed only if the
``__livepatch__`` function is declared to take such named arguments or it takes
\**kwargs.  If the ``__livepatch__`` function takes \**kwargs, it should ignore
unknown arguments, in case new parameters are added in the future.

If the object being updated is an object instance, and ``__livepatch__`` is a
method, then the function is bound to the new object, i.e. the ``self``
parameter is the same as ``new``.

If the ``__livepatch__`` function successfully patched the ``old`` object, then
it should return ``old``.  If it is unable to patch, it should return ``new``.

Examples
--------

By default, any attributes on an existing function are updated with ones from
the new function.  If you want a memoized function to keep its cache across
xreload, you could implement that like this::

  def memoize(function):
      cache = {}
      def wrapped_fn(*args):
          try:
              return cache[args]
          except KeyError:
              result = function(*args)
              cache[args] = result
              return result
      wrapped_fn.cache = cache
      def my_livepatch(old, new, do_livepatch):
          keep_cache = dict(old.cache)
          result = do_livepatch()
          result.cache.update(keep_cache)
          return result
      wrapped_fn.__livepatch__ = my_livepatch
      return wrapped_fn

XXX change example b/c cache is already cleared by default
XXX maybe global cache

  class MyObj(...):
      def __livepatch__(self, old):
          self.__dict__.update(old.__dict__)
          return self

  class MyObj(...):
      def __init__(self):
          self._my_cache = {}

      def __livepatch__(self, old, do_livepatch):
          keep_cache = dict(old._my_cache)
          result = do_livepatch()
          result._my_cache.update(keep_cache)
          return result

XXX test

"""



import ast
import os
import re
import sys
import time
import types

from   importlib                import reload as reload_module

import inspect
from   pyflyby._log             import logger


# Keep track of when the process was started.
if os.uname()[0] == 'Linux':
    _PROCESS_START_TIME = os.stat("/proc/%d"%os.getpid()).st_ctime
else:
    try:
        import psutil
    except ImportError:
        # Todo: better fallback
        _PROCESS_START_TIME = time.time()
    else:
        _PROCESS_START_TIME = psutil.Process(os.getpid()).create_time()


class UnknownModuleError(ImportError):
    pass


def livepatch(old, new, modname=None,
              visit_stack=(), cache=None, assume_type=None,
              heed_hook=True):
    """
    Livepatch ``old`` with contents of ``new``.

    If ``old`` can't be livepatched, then return ``new``.

    :param old:
      The object to be updated
    :param new:
      The object used as the source for the update.
    :type modname:
      ``str``
    :param modname:
      Only livepatch ``old`` if it was defined in the given fully-qualified
      module name.  If ``None``, then update regardless of module.
    :param assume_type:
      Update as if both ``old`` and ``new`` were of type ``assume_type``.  If
      ``None``, then ``old`` and ``new`` must have the same type.
      For internal use.
    :param cache:
      Cache of already-updated objects.  Map from (id(old), id(new)) to result.
    :param visit_stack:
      Ids of objects that are currently being updated.
      Used to deal with reference cycles.
      For internal use.
    :param heed_hook:
      If ``True``, heed the ``__livepatch__`` hook on ``new``, if any.
      If ``False``, ignore any ``__livepatch__`` hook on ``new``.
    :return:
      Either live-patched ``old``, or ``new``.
    """
    if old is new:
        return new
    # If we're already visiting this object (due to a reference cycle), then
    # don't recurse again.
    if id(old) in visit_stack:
        return old
    if cache is None:
        cache = {}
    cachekey = (id(old), id(new))
    try:
        return cache[cachekey]
    except KeyError:
        pass
    visit_stack += (id(old),)
    def do_livepatch():
        new_modname = _get_definition_module(new)
        if modname and new_modname and new_modname != modname:
            # Ignore objects that have been imported from another module.
            # Just update their references.
            return new
        if assume_type is not None:
            use_type = assume_type
        else:
            oldtype = type(old)
            newtype = type(new)
            if oldtype is newtype:
                # Easy, common case: Type didn't change.
                use_type = oldtype
            elif (oldtype.__name__ == newtype.__name__ and
                  oldtype.__module__ == newtype.__module__ == modname and
                  getattr(sys.modules[modname],
                          newtype.__name__, None) is newtype and
                  oldtype is livepatch(
                      oldtype, newtype, modname=modname,
                      visit_stack=visit_stack, cache=cache)):
                # Type of this object was defined in this module.  This
                # includes metaclasses defined in the same module.
                use_type = oldtype
            else:
                # If the type changed, then give up.
                return new
        try:
            mro = type.mro(use_type)
        except TypeError:
            mro = [use_type, object] # old-style class
        # Dispatch on type.  Include parent classes (in C3 linearized
        # method resolution order), in particular so that this works on
        # classes with custom metaclasses that subclass ``type``.
        for t in mro:
            try:
                update = _LIVEPATCH_DISPATCH_TABLE[t]
                break
            except KeyError:
                pass
        else:
            # We should have found at least ``object``
            raise AssertionError("unreachable")
        # Dispatch.
        return update(old, new, modname=modname,
                      cache=cache, visit_stack=visit_stack)
    if heed_hook:
        hook = (getattr(new, "__livepatch__", None) or
                getattr(new, "__reload_update__", None))
        # XXX if unbound method or a descriptor, then we should ignore it.
        # XXX test for that.
    else:
        hook = None
    if hook is None:
        # No hook is defined or the caller instructed us to ignore it.
        # Do the standard livepatch.
        result = do_livepatch()
    else:
        # Call a hook for updating.
        # Build dict of optional kwargs.
        avail_kwargs = dict(
            old=old,
            new=new,
            do_livepatch=do_livepatch,
            modname=modname,
            cache=cache,
            visit_stack=visit_stack)
        # Find out which optional kwargs the hook wants.
        kwargs = {}
        argspec = inspect.getfullargspec(hook)
        argnames = argspec.args
        if hasattr(hook, "__func__"):
            # Skip 'self' arg.
            argnames = argnames[1:]
        # Pick kwargs that are wanted and available.
        args = []
        kwargs = {}
        for n in argnames:
            try:
                kwargs[n] = avail_kwargs[n]
                if argspec.varkw:
                    break
            except KeyError:
                # For compatibility, allow first argument to be 'old' with any
                # name, as long as there's no other arg 'old'.
                # We intentionally allow this even if the user specified
                # **kwargs.
                if not args and not kwargs and 'old' not in argnames:
                    args.append(old)
                else:
                    # Rely on default being set.  If a default isn't set, the
                    # user will get a TypeError.
                    pass
        if argspec.varkw:
            # Use all available kwargs.
            kwargs = avail_kwargs
        # Call hook.
        result = hook(*args, **kwargs)
    cache[cachekey] = result
    return result


def _livepatch__module(old_mod, new_mod, modname, cache, visit_stack):
    """
    Livepatch a module.
    """
    result = livepatch(old_mod.__dict__, new_mod.__dict__,
                       modname=modname,
                       cache=cache, visit_stack=visit_stack)
    assert result is old_mod.__dict__
    return old_mod


def _livepatch__dict(old_dict, new_dict, modname, cache, visit_stack):
    """
    Livepatch a dict.
    """
    oldnames = set(old_dict)
    newnames = set(new_dict)
    # Add newly introduced names.
    for name in newnames - oldnames:
        old_dict[name] = new_dict[name]
    # Delete names that are no longer current.
    for name in oldnames - newnames:
        del old_dict[name]
    # Livepatch existing entries.
    updated_names = sorted(oldnames & newnames, key=str)
    for name in updated_names:
        old = old_dict[name]
        updated = livepatch(old, new_dict[name],
                            modname=modname,
                            cache=cache, visit_stack=visit_stack)
        if updated is not old:
            old_dict[name] = updated
    return old_dict


def _livepatch__function(old_func, new_func, modname, cache, visit_stack):
    """
    Livepatch a function.
    """
    # If the name differs, then don't update the existing function - this
    # is probably a reassigned function.
    if old_func.__name__ != new_func.__name__:
        return new_func
    # Check if the function's closure is compatible.  If not, then return the
    # new function without livepatching.  Note that cell closures can't be
    # modified; we can only livepatch cell values.
    old_closure = old_func.__closure__ or ()
    new_closure = new_func.__closure__ or ()
    if len(old_closure) != len(new_closure):
        return new_func
    if old_func.__code__.co_freevars != new_func.__code__.co_freevars:
        return new_func
    for oldcell, newcell in zip(old_closure, new_closure):
        oldcellv = oldcell.cell_contents
        newcellv = newcell.cell_contents
        if type(oldcellv) != type(newcellv):
            return new_func
        if isinstance(oldcellv, (
                types.FunctionType, types.MethodType, type, dict)):
            # Updateable type.  (Todo: make this configured globally.)
            continue
        try:
            if oldcellv is newcellv or oldcellv == newcellv:
                continue
        except Exception:
            pass
        # Non-updateable and not the same as before.
        return new_func
    # Update function code, defaults, doc.
    old_func.__code__ = new_func.__code__
    old_func.__defaults__ = new_func.__defaults__
    old_func.__doc__ = new_func.__doc__
    # Update dict.
    livepatch(old_func.__dict__, new_func.__dict__,
              modname=modname, cache=cache, visit_stack=visit_stack)
    # Update the __closure__.  We can't set __closure__ because it's a
    # read-only attribute; we can only livepatch its cells' values.
    for oldcell, newcell in zip(old_closure, new_closure):
        oldcellv = oldcell.cell_contents
        newcellv = newcell.cell_contents
        livepatch(oldcellv, newcellv,
                  modname=modname, cache=cache, visit_stack=visit_stack)
    return old_func


def _livepatch__method(old_method, new_method, modname, cache, visit_stack):
    """
    Livepatch a method.
    """
    _livepatch__function(old_method.__func__, new_method.__func__,
                         modname=modname,
                         cache=cache, visit_stack=visit_stack)
    return old_method


def _livepatch__setattr(oldobj, newobj, name, modname, cache, visit_stack):
    """
    Livepatch something via setattr, i.e.::

       oldobj.{name} = livepatch(oldobj.{name}, newobj.{name}, ...)
    """
    newval = getattr(newobj, name)
    assert type(newval) is not types.MemberDescriptorType
    try:
        oldval = getattr(oldobj, name)
    except AttributeError:
        # This shouldn't happen, but just ignore it.
        setattr(oldobj, name, newval)
        return
    # If it's the same object, then skip.  Note that if even if 'newval ==
    # oldval', as long as they're not the same object instance, we still
    # livepatch.  We want mutable data structures get livepatched instead of
    # replaced.  Avoiding calling '==' also avoids the risk of user code
    # having defined '==' to do something unexpected.
    if newval is oldval:
        return
    # Livepatch the member object.
    newval = livepatch(
        oldval, newval, modname=modname, cache=cache, visit_stack=visit_stack)
    # If the livepatch succeeded then we don't need to setattr.  It should be
    # a no-op but we avoid it just to minimize any chance of setattr causing
    # problems in corner cases.
    if newval is oldval:
        return
    # Livepatch failed, so we have to update the container with the new member
    # value.
    setattr(oldobj, name, newval)


def _livepatch__class(oldclass, newclass, modname, cache, visit_stack):
    """
    Livepatch a class.

    This is similar to _livepatch__dict(oldclass.__dict__, newclass.__dict__).
    However, we can't just operate on the dict, because class dictionaries are
    special objects that don't allow setitem, even though we can setattr on
    the class.
    """
    # Collect the names to update.
    olddict = oldclass.__dict__
    newdict = newclass.__dict__
    # Make sure slottiness hasn't changed -- i.e. if class was changed to have
    # slots, or changed to not have slots, or if the slot names changed in any
    # way, then we can't livepatch the class.
    # Note that this is about whether instances of this class are affected by
    # __slots__ or not.  The class type itself will always use a __dict__.
    if olddict.get("__slots__") != newdict.get("__slots__"):
        return newclass
    oldnames = set(olddict)
    newnames = set(newdict)
    for name in oldnames - newnames:
        delattr(oldclass, name)
    for name in newnames - oldnames:
        setattr(oldclass, name, newdict[name])
    oldclass.__bases__ = newclass.__bases__
    names = oldnames & newnames
    names.difference_update(olddict.get("__slots__", []))
    names.discard("__slots__")
    names.discard("__dict__")
    # Python < 3.3 doesn't support modifying __doc__ on classes with
    # non-custom metaclasses.  Attempt to do it and ignore failures.
    # http://bugs.python.org/issue12773
    names.discard("__doc__")
    try:
        oldclass.__doc__ = newclass.__doc__
    except AttributeError:
        pass
    # Loop over attributes to be updated.
    for name in sorted(names):
        _livepatch__setattr(
            oldclass, newclass, name, modname, cache, visit_stack)
    return oldclass


def _livepatch__object(oldobj, newobj, modname, cache, visit_stack):
    """
    Livepatch a general object.
    """
    # It's not obvious whether ``oldobj`` and ``newobj`` are actually supposed
    # to represent the same object.  For now, we take a middle ground of
    # livepatching iff the class was also defined in the same module.  In that
    # case at least we know that the object was defined in this module and
    # therefore more likely that we should livepatch.
    if modname and _get_definition_module(type(oldobj)) != modname:
        return newobj
    if hasattr(type(oldobj), "__slots__"):
        assert oldobj.__slots__ == newobj.__slots__
        for name in newobj.__slots__:
            hasold = hasattr(oldobj, name)
            hasnew = hasattr(newobj, name)
            if hasold and hasnew:
                _livepatch__setattr(oldobj, newobj, name,
                                          modname, cache, visit_stack)
            elif hasold and not hasnew:
                delattr(oldobj, name)
            elif not hasold and hasnew:
                setattr(oldobj, getattr(newobj, name))
            elif not hasold and not hasnew:
                pass
            else:
                raise AssertionError
        return oldobj
    elif type(getattr(oldobj, "__dict__", None)) is dict:
        livepatch(
            oldobj.__dict__, newobj.__dict__,
            modname=modname, cache=cache, visit_stack=visit_stack)
        return oldobj
    else:
        return newobj

_LIVEPATCH_DISPATCH_TABLE = {
    object            : _livepatch__object,
    dict              : _livepatch__dict,
    type              : _livepatch__class,
    types.FunctionType: _livepatch__function,
    types.MethodType  : _livepatch__method,
    types.ModuleType  : _livepatch__module,
}


def _get_definition_module(obj):
    """
    Get the name of the module that an object is defined in, or ``None`` if
    unknown.

    For classes and functions, this returns the ``__module__`` attribute.

    For object instances, this returns ``None``, ignoring the ``__module__``
    attribute.  The reason is that the ``__module__`` attribute on an instance
    just gives the module that the class was defined in, which is not
    necessarily the module where the instance was constructed.

    :rtype:
      ``str``
    """
    if isinstance(obj, (type, types.FunctionType,
                        types.MethodType)):
        return getattr(obj, "__module__", None)
    else:
        return None


def _format_age(t):
    secs = time.time() - t
    if secs > 120:
        return "%dm%ds" %(secs//60, secs%60)
    else:
        return "%ds" %(secs,)


def _interpret_module(arg):
    def mod_fn(module):
        return getattr(module, "__file__", None)

    if isinstance(arg, str):
        try:
            return sys.modules[arg]
        except KeyError:
            pass
        if arg.startswith("/"):
            fn = os.path.realpath(arg)
            if fn.endswith(".pyc") or fn.endswith(".pyo"):
                fn = fn[:-1]
            if fn.endswith(".py"):
                relevant_fns = set([fn, fn+"c", fn+"o"])
            else:
                relevant_fns = set([fn])
            found_modules = [
                m for _,m in sorted(sys.modules.items())
                if os.path.realpath(mod_fn(m) or "/") in relevant_fns ]
            if not found_modules:
                raise UnknownModuleError(
                    "No loaded module uses path %s" % (fn,))
            if len(found_modules) > 1:
                raise UnknownModuleError(
                    "Multiple loaded modules use path %s: %r"
                    % (fn, found_modules))
            return found_modules[0]
        if arg.endswith(".py") and "/" not in arg:
            name = arg[:-3]
            relevant_bns = set([arg, arg+"c", arg+"o"])
            found_modules = [
                m for n,m in sorted(sys.modules.items())
                if (n==name or
                    os.path.basename(mod_fn(m) or "/") in relevant_bns)]
            if not found_modules:
                raise UnknownModuleError(
                    "No loaded module named %s" % (name,))
            if len(found_modules) > 1:
                raise UnknownModuleError(
                    "Multiple loaded modules named %s: %r"
                    % (name, found_modules))
            return found_modules[0]
        raise UnknownModuleError(arg)
    if isinstance(arg, types.ModuleType):
        return arg
    try:
        # Allow fake modules.
        if sys.modules[arg.__name__] is arg:
            return arg
    except Exception:
        pass
    raise TypeError("Expected module, module name, or filename; got %s"
                    % (type(arg).__name__))


def _xreload_module(module, filename, force=False):
    """
    Reload a module in place, using livepatch.

    :type module:
      ``ModuleType``
    :param module:
      Module to reload.
    :param force:
      Whether to reload even if the module has not been modified since the
      previous load.  If ``False``, then do nothing.  If ``True``, then reload.
    """
    import linecache
    if not filename or not filename.endswith(".py"):
        # If there's no *.py source file for this module, then fallback to
        # built-in reload().
        return reload_module(module)
    # Compare mtime of the file with the load time of the module.  If the file
    # wasn't touched, we don't need to do anything.
    try:
        mtime = os.stat(filename).st_mtime
    except OSError:
        logger.info("Can't find %s", filename)
        return None
    if not force:
        try:
            old_loadtime = module.__loadtime__
        except AttributeError:
            # We only have a __loadtime__ attribute if we were the ones that
            # loaded it.  Otherwise, fall back to the process start time as a
            # conservative bound.
            old_loadtime = _PROCESS_START_TIME
        if old_loadtime > mtime:
            logger.debug(
                "NOT reloading %s (file %s modified %s ago but loaded %s ago)",
                module.__name__, filename, _format_age(mtime),
                _format_age(old_loadtime))
            return None
        # Keep track of previously imported source.  If the file's timestamp
        # was touched, but the content unchanged, we can avoid reloading.
        cached_lines = linecache.cache.get(filename, (None,None,None,None))[2]
    else:
        cached_lines = None
    # Re-read source for module from disk, and update the linecache.
    source = ''.join(linecache.updatecache(filename))
    # Skip reload if the content didn't change.
    if cached_lines is not None and source == ''.join(cached_lines):
        logger.debug(
            "NOT reloading %s (file %s touched %s ago but content unchanged)",
            module.__name__, filename, _format_age(mtime))
        return module
    logger.info("Reloading %s (modified %s ago) from %s",
                module.__name__, _format_age(mtime), filename)
    # Compile into AST.  We do this as a separate step from compiling to byte
    # code so that we can get the module docstring.
    astnode = compile(source, filename, "exec", ast.PyCF_ONLY_AST, 1)
    # Get the new docstring.
    try:
        if sys.versin_info > (3,10):
            doc = astnode.body[0].value.value
        else:
            doc = astnode.body[0].value.s
    except (AttributeError, IndexError):
        doc = None
    # Compile into code.
    code = compile(astnode, filename, "exec", 0, 1)
    # Execute the code.  We do so in a temporary namespace so that if this
    # fails, nothing changes.  It's important to set __name__ so that relative
    # imports work correctly.
    new_mod = types.ModuleType(module.__name__)
    new_mod.__file__ = filename
    new_mod.__doc__ = doc
    if hasattr(module, "__path__"):
        new_mod.__path__ = module.__path__
    MISSING = object()
    saved_mod = sys.modules.get(module.__name__, MISSING)
    try:
        # Temporarily put the temporary module in sys.modules, in case the
        # code references sys.modules[__name__] for some reason.  Normally on
        # success, we will revert this what that was there before (which
        # normally should be ``module``).  If an error occurs, we'll also
        # revert.  If the user has defined a __livepatch__ hook at the module
        # level, it's possible for result to not be the old module.
        sys.modules[module.__name__] = new_mod
        # *** Execute new code ***
        exec(code, new_mod.__dict__)
        # Normally ``module`` is of type ``ModuleType``.  However, in some
        # cases, the module might have done a "proxy module" trick where the
        # module is replaced by a proxy object of some other type.  Regardless
        # of the actual type, we do the update as ``module`` were of type
        # ``ModuleType``.
        assume_type = types.ModuleType
        # Livepatch the module.
        result = livepatch(module, new_mod, module.__name__,
                           assume_type=assume_type)
        sys.modules[module.__name__] = result
    except:
        # Either the module failed executing or the livepatch failed.
        # Revert to previous state.
        # Note that this isn't perfect because it's possible that the module
        # modified some global state in other modules.
        if saved_mod is MISSING:
            del sys.modules[module.__name__]
        else:
            sys.modules[module.__name__] = saved_mod
        raise
    # Update the time we last loaded the module.  We intentionally use mtime
    # here instead of time.time().  If we are on NFS, it's possible for the
    # filer's mtime and time.time() to not be synchronized.  We will be
    # comparing to mtime next time, so if we use only mtime, we'll be fine.
    module.__loadtime__ = mtime
    return module


def _get_module_py_file(module):
    filename = getattr(module, "__file__", None)
    if not filename:
        return None
    filename = re.sub("[.]py[co]$", ".py", filename)
    return filename


def xreload(*args):
    """
    Reload module(s).

    This function is more useful than the built-in reload().  xreload() uses a
    "live patch" approach that modifies existing functions, classes, and
    objects in-place.

    This addresses cases where one module imported functions from another
    module.

    For example, suppose m1.py contains::

      from m2 import foo
      def print_foo():
          return foo()

    and m2.py contains::

      def foo():
          return 42

    If you edit m2.py and modify ``foo``, then reload(m2) on its own would not
    do what you want.  The built-in reload affects the module being reloaded,
    but references to the old module remain.  On the other hand, xreload()
    patches the existing m2.foo, so that live references to it are updated.

    :type args:
      ``str`` s and/or ``ModuleType`` s
    :param args:
      Module(s) to reload.  If no argument is specified, then reload all
      recently modified modules.
    """
    if not args:
        for name, module in sorted(sys.modules.items()):
            if name == "__main__":
                continue
            filename = _get_module_py_file(module)
            if not filename:
                continue
            _xreload_module(module, filename)
        return
    # Treat xreload(list_of_module) like xreload(*list_of_modules).  We
    # intentionally do this after the above check so that xreload([]) does
    # nothing.
    if len(args) == 1 and isinstance(args[0], (tuple, list)):
        args = args[0]
    for arg in args:
        module = _interpret_module(arg)
        # Get the *.py filename for this module.
        filename = _get_module_py_file(module)
        # Reload the module.
        _xreload_module(module, filename)
