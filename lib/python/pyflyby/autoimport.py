"""
AUTOMATIC IMPORTS - never type "import" again!

This module allows your "known imports" to work automatically in your IPython
interactive session without having to type the 'import' statements (and also
without having to slow down your Python startup with imports you only use
occasionally).

To use, add to your IPython startup::
  from pyflyby.autoimport import install_auto_importer
  install_auto_importer()

Example:

  In [1]: re.search("[a-z]+", "....hello...").group(0)
  [AUTOIMPORT] import re
  Out[1]: 'hello'

  In [2]: chisqprob(arange(5), 2)
  [AUTOIMPORT] from numpy import arange
  [AUTOIMPORT] from scipy.stats import chisqprob
  Out[2]: [ 1.      0.6065  0.3679  0.2231  0.1353]

  In [3]: np.sin(arandom(5))
  [AUTOIMPORT] from numpy.random import random as arandom
  [AUTOIMPORT] import numpy as np
  Out[3]: [ 0.0282  0.0603  0.4653  0.8371  0.3347]

  In [4]: isinstance(42, Number)
  [AUTOIMPORT] from numbers import Number
  Out[4]: True


It works as you expect
======================

Tab completion works, even on modules that are not yet imported.  In the
following example, notice that numpy is imported when we need to know its
members, and only then:

  In [1]: nump<TAB>
  In [1]: numpy
  In [1]: numpy.arang<TAB>
  [AUTOIMPORT] import numpy
  In [1]: numpy.arange


The IPython "?" magic help (pinfo/pinfo2) automatically imports symbols first
if necessary:

  In [1]: arange?
  [AUTOIMPORT] from numpy import arange
  ... Docstring: arange([start,] stop[, step,], dtype=None) ...


Implementation details
======================

The automatic importing happens at parse time, before code is executed.  The
namespace never contains entries for names that are not yet imported.

This method of importing at parse time contrasts with previous implementations
of automatic importing that use proxy objects.  Those implementations using
proxy objects don't work as well, because it is impossible to make proxy
objects behave perfectly.  For example, instance(x, T) will return the wrong
answer if either x or T is a proxy object.


"""

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __builtin__
import ast
import os
import sys
import types

import contextlib
from   pyflyby.util             import dotted_prefixes, is_identifier, memoize


# TODO: also support arbitrary code (in the form of a lambda and/or
# assignment) as new way to do "lazy" creations, e.g. foo = a.b.c(d.e+f.g())


debugging_enabled = bool(os.environ.get("PYFLYBY_AUTOIMPORT_DEBUG", ""))

output_function = print
"""
Function that prints a single line.
"""

@contextlib.contextmanager
def InterceptPrintsDuringPromptCtx():
    """
    Hook our local output function so that:
      1. Before the first print, if any, print an extra newline.
      2. Upon context exit, if any lines were printed, redisplay the prompt.
    """
    global output_function
    print_count = [0]
    ip = get_ipython_safe()
    try:
        readline       = ip.readline
        prompt_manager = ip.prompt_manager
        redisplay      = readline.redisplay
        input_splitter = ip.input_splitter
    except AttributeError:
        yield
        return
    def output_during_prompt(line):
        if not print_count[0]:
            print()
        print(line)
        print_count[0] += 1
    orig_output_function = output_function
    output_function = output_during_prompt
    try:
        yield
    finally:
        output_function = orig_output_function
        if print_count[0]:
            # Re-display the current line.
            if input_splitter.source == "":
                # First line
                prompt = ip.separate_in + prompt_manager.render("in")
            else:
                # Non-first line
                prompt = prompt_manager.render("in2")
            line = readline.get_line_buffer()
            sys.stdout.write(prompt + line)
            redisplay()


def debug(fmt, *args):
    if debugging_enabled:
        try:
            msg = fmt % args
        except Exception as e:
            msg = "%s  [%s: %s]" % (fmt, type(e).__name__, e)
        output_function("[AUTOIMPORT DEBUG] %s" % (msg,))


def info(fmt, *args):
    try:
        msg = fmt % args
    except Exception as e:
        msg = "%s  [%s: %s]" % (fmt, type(e).__name__, e)
    output_function("[AUTOIMPORT] %s" % (msg,))



@memoize
def get_ipython_safe():
    """
    Get an IPython shell instance, if we are inside an IPython session.

    If we are not inside an IPython session, don't initialize one.

    @rtype:
      C{IPython.core.interactiveshell.InteractiveShell}
    """
    try:
        IPython = sys.modules['IPython']
    except KeyError:
        # The 'IPython' module isn't already loaded, so we're not in an
        # IPython session.  Don't import it.
        debug("[IPython not loaded]")
        return None
    # IPython 1.0+: use IPython.get_ipython().  This doesn't create an
    # instance if it doesn't already exist.
    try:
        get_ipython = IPython.get_ipython
    except AttributeError:
        pass
    else:
        return get_ipython()
    # IPython 0.11+: IPython.core.interactiveshell.InteractiveShell._instance.
    # [The public method IPython.core.ipapi.get() also returns this, but we
    # don't want to call that, because get() creates an IPython shell if it
    # doesn't already exist, which we don't want.]
    try:
        return IPython.core.interactiveshell.InteractiveShell._instance
    except AttributeError:
        pass
    # IPython 0.10+: IPython.ipapi.get
    try:
        get = IPython.ipapi.get
    except AttributeError:
        pass
    else:
        ipsh = get()
        if ipsh is not None:
            return ipsh.IP
    # Couldn't get IPython.
    debug("Couldn't get IPython shell instance (IPython version: %s)",
          IPython.__version__)
    return None


def _ipython_namespaces(ip):
    """
    Return the (global) namespaces used for IPython.

    The ordering follows IPython convention of most-local to most-global.

    @type ip:
      C{IPython.core.InteractiveShell}
    @rtype:
      C{list}
    @return:
      List of (name, namespace_dict) tuples.
    """
    # This list is copied from IPython 1.2's InteractiveShell._ofind().
    return [ ('Interactive'         , ip.user_ns),
             ('Interactive (global)', ip.user_global_ns),
             ('Python builtin'      , __builtin__.__dict__),
             ('Alias'               , ip.alias_manager.alias_table),
    ]


def interpret_namespaces(namespaces):
    """
    Interpret the input argument as a stack of namespaces.  It is normally
    ordered from most-global to most-local.

    If C{None}, then use get_ipython().user_global_ns for IPython and
    __main__.__dict__ for regular Python.

    Always include builtins.
    Duplicates are removed.

    @type namespaces:
      C{dict}, C{list} of C{dict}, or C{None}
    @param namespaces:
      Input namespaces
    @rtype:
      C{list} of C{dict}
    """
    if namespaces is None:
        ip = get_ipython_safe()
        if ip:
            namespaces = [ns for nsname, ns in _ipython_namespaces(ip)][::-1]
        else:
            import __main__
            namespaces = [__builtin__.__dict__, __main__.__dict__]
    if isinstance(namespaces, dict):
        namespaces = [namespaces]
    if not isinstance(namespaces, list):
        raise TypeError("Expected dict or list of dicts; got a %s"
                        % type(namespaces).__name__)
    if not all(isinstance(ns, dict) for ns in namespaces):
        raise TypeError("Expected dict or list of dicts; got a sequence of %r"
                        % ([type(x).__name__ for x in namespaces]))
    namespaces = [__builtin__.__dict__] + namespaces
    result = []
    seen = set()
    # Keep only unique items, checking uniqueness by object identity.
    for ns in namespaces:
        if id(ns) in seen:
            continue
        seen.add(id(ns))
        result.append(ns)
    return result


def symbol_needs_import(fullname, namespaces=None):
    """
    Return whether C{fullname} is a symbol that needs to be imported, given
    the current namespace scopes.

    A symbol needs importing if it is not previously imported or otherwise
    assigned.  C{namespaces} normally includes builtins and globals as well as
    symbols imported/assigned locally within the scope.

    If the user requested "foo.bar.baz", and we see that "foo.bar" exists
    and is not a module, we assume nothing under foo.bar needs import.
    This is intentional because (1) the import would not match what is
    already in the namespace, and (2) we don't want to do call
    getattr(foo.bar, "baz"), since that could invoke code that is slow or
    has side effects.

    @type fullname:
      C{str}
    @param fullname:
      Fully-qualified symbol name, e.g. "os.path.join".
    @type namespaces:
      C{list} of C{dict}
    @param namespaces:
      Stack of namespaces to search for existing items.
    @rtype:
      C{bool}
    @return:
      C{True} if C{fullname} needs import, else C{False}
    """
    namespaces = interpret_namespaces(namespaces)
    partial_names = dotted_prefixes(fullname, reverse=True)
    # Iterate over local scopes.
    for ns_idx, ns in enumerate(namespaces):
        # Iterate over partial names: "foo.bar.baz.quux", "foo.bar.baz", ...
        for partial_name in partial_names:
            # Check if this partial name was imported/assigned in this
            # scope.  In the common case, there will only be one namespace
            # in the namespace stack, i.e. the user globals.
            try:
                var = ns[partial_name]
            except KeyError:
                continue
            # Suppose the user accessed fullname="foo.bar.baz.quux" and
            # suppose we see "foo.bar" was imported (or otherwise assigned) in
            # the scope vars (most commonly this means it was imported
            # globally).  Let's check if foo.bar already has a "baz".
            prefix_len = len(partial_name.split("."))
            suffix_parts = fullname.split(".")[prefix_len:]
            pname = partial_name
            for part in suffix_parts:
                if not isinstance(var, types.ModuleType):
                    # The variable is not a module.  (If this came from a
                    # local assignment then C{var} will just be "None"
                    # here to indicate we know it was assigned but don't
                    # know about its type.)  Thus nothing under it needs
                    # import.
                    debug("symbol_needs_import(%r): %s is in namespace %d (under %r) and not a module, so it doesn't need import", fullname, pname, ns_idx, partial_name)
                    return False
                try:
                    var = getattr(var, part)
                except AttributeError:
                    # We saw that "foo.bar" is imported, and is a module,
                    # but it does not have a "baz" attribute.  Thus, as we
                    # know so far, foo.bar.baz requires import.  But
                    # continue on to the next scope.
                    debug("symbol_needs_import(%r): %s is a module in namespace %d (under %r), but has no %r attribute", fullname, pname, ns_idx, partial_name, part)
                    break # continue outer loop
                pname = "%s.%s" % (pname, part)
            else:
                # We saw that "foo.bar" is imported, and checked that
                # foo.bar has an attribute "baz", which has an
                # attribute "quux" - so foo.bar.baz.quux does not need
                # to be imported.
                assert pname == fullname
                debug("symbol_needs_import(%r): found it in namespace %d (under %r), so it doesn't need import", fullname, ns_idx, partial_name)
                return False
    # We didn't find any scope that defined the name.  Therefore it needs
    # import.
    debug("symbol_needs_import(%r): no match found in namespaces; it needs import", fullname)
    return True


class _MissingImportFinder(ast.NodeVisitor):
    """
    A helper class to be used only by L{find_missing_imports_in_ast}.

    This class visits every AST node and collects symbols that require
    importing.  A symbol requires importing if it is not already imported or
    otherwise defined/assigned in this scope.

    For attributes like "foo.bar.baz", we need to be more sophisticated:
    Suppose the user imports "foo.bar" and then accesses "foo.bar.baz.quux".
    Baz may be already available just by importing foo.bar, or it may require
    further import.  We decide as follows.  If foo.bar is not a module, then
    we assume whatever's under it can't be imported.  If foo.bar is a module
    but does not have a 'baz' attribute, then it does require import.

    """

    def __init__(self, namespaces):
        """
        Construct the AST visitor.

        @type namespaces:
          C{dict} or C{list} of C{dict}
        @param namespaces:
          User globals
        """
        # Create a stack of namespaces.  The caller should pass in a list that
        # includes the globals dictionary.  interpret_namespaces() will make
        # sure this includes builtins.  Add an empty dictionary to the stack.
        # This is to allow ourselves to add stuff to ns_stack[-1] without ever
        # modifying user globals.  We will also mutate ns_stack, so it should
        # be a newly constructed list.
        namespaces = interpret_namespaces(namespaces)
        self.ns_stack = namespaces + [{}]
        # Create data structure to hold the result.  Caller will read this.
        self.missing_imports = set()

    def _visit_new_scope(self, node):
        # Push a new empty namespace onto the stack of namespaces.
        this_ns = {}
        self.ns_stack.append(this_ns)
        self.generic_visit(node)
        assert self.ns_stack[-1] is this_ns
        del self.ns_stack[-1]

    visit_Lambda = _visit_new_scope
    visit_ListComp = _visit_new_scope
    visit_GeneratorExp = _visit_new_scope

    def visit_ClassDef(self, node):
        self._visit_Store(node.name)
        self._visit_new_scope(node)

    def visit_FunctionDef(self, node):
        self._visit_Store(node.name)
        self._visit_new_scope(node)

    def visit_arguments(self, node):
        self._visit_Store(node.vararg)
        self._visit_Store(node.kwarg)
        self.generic_visit(node)

    def visit_alias(self, node):
        # TODO: Currently we treat 'import foo' the same as if the user did
        # 'foo = 123', i.e. we treat it as a black box (non-module).  This is
        # to avoid actually importing it yet.  But this means we won't know
        # whether foo.bar is available so we won't auto-import it.  Maybe we
        # should give up on not importing it and just import it in a scratch
        # namespace, so we can check.
        self._visit_Store(node.asname or node.name)
        self.generic_visit(node)

    def visit_Name(self, node):
        debug("visit_Name(%r)", node.id)
        self._visit_fullname(node.id, node.ctx)

    def visit_Attribute(self, node):
        debug("visit_Attribute(%r)", node.attr)
        name_revparts = []
        n = node
        while isinstance(n, ast.Attribute):
            name_revparts.append(n.attr)
            n = n.value
        if not isinstance(n, ast.Name):
            # Attribute of a non-symbol, e.g. (a+b).c
            # We do nothing about "c", but we do recurse on (a+b) since those
            # may have symbols we care about.
            self.generic_visit(node)
            return
        name_revparts.append(n.id)
        name_parts = name_revparts[::-1]
        fullname = ".".join(name_parts)
        self._visit_fullname(fullname, node.ctx)

    def _visit_fullname(self, fullname, ctx):
        if isinstance(ctx, (ast.Store, ast.Param)):
            self._visit_Store(fullname)
        elif isinstance(ctx, ast.Load):
            self._visit_Load(fullname)

    def _visit_Store(self, fullname):
        debug("_visit_Store(%r)", fullname)
        self.ns_stack[-1][fullname] = None

    def _visit_Load(self, fullname):
        debug("_visit_Load(%r)", fullname)
        if symbol_needs_import(fullname, self.ns_stack):
            self.missing_imports.add(fullname)


def find_missing_imports(arg, namespaces=None):
    """
    Find symbols in the given code that require import.

    We consider a symbol to require import if we see an access ("Load" in AST
    terminology) without an import or assignment ("Store" in AST terminology)
    in the same lexical scope.

    For example, if we use an empty list of namespaces, then "os.path.join" is
    a symbol that requires import:
      >>> find_missing_imports("os.path.join", namespaces=[])
      ['os.path.join']

    But if the global namespace already has the "os" module imported, then we
    know that C{os} has a "path" attribute, which has a "join" attribute, so
    nothing needs import:
      >>> find_missing_imports("os.path.join", namespaces=[{"os":os}])
      []

    Builtins are always included:
      >>> find_missing_imports("os, sys, eval", [{"os": os}])
      ['sys']

    All symbols that are not defined are included:
      >>> find_missing_imports("numpy.arange(x) + arange(y)", [{"y": 3}])
      ['arange', 'numpy.arange', 'x']

    If something is imported/assigned/etc within the scope, then we assume it
    doesn't require importing:
      >>> find_missing_imports("import numpy; numpy.arange(x) + arange(x)", [])
      ['arange', 'x']

      >>> find_missing_imports("from numpy import pi; numpy.pi + pi + x", [])
      ['numpy.pi', 'x']

      >>> find_missing_imports("for x in range(3): print numpy.arange(x)", [])
      ['numpy.arange']

      >>> find_missing_imports("foo1 = func(); foo1.bar + foo2.bar", [])
      ['foo2.bar', 'func']

      >>> find_missing_imports("a.b.y = 1; a.b.x, a.b.y, a.b.z", [])
      ['a.b.x', 'a.b.z']

    find_missing_imports() parses the AST, so it understands scoping.  In the
    following example, C{x} is never undefined:
      >>> find_missing_imports("(lambda x: x*x)(7)", [])
      []

    but this example, C{x} is undefined at global scope:
      >>> find_missing_imports("(lambda x: x*x)(7) + x", [])
      ['x']

    Only fully-qualified names starting at top-level are included:

      >>> find_missing_imports("( ( a . b ) . x ) . y + ( c + d ) . x . y")
      ['a.b.x.y', 'c', 'd']

    @type arg:
      C{str} or C{ast.AST}
    @param arg:
      Python code text (as simple as a single qualified name, or as complex as
      an entire module text) or an AST node
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Stack of namespaces of symbols that exist per scope.
    @rtype:
      C{list} of C{str}
    """
    namespaces = interpret_namespaces(namespaces)
    if isinstance(arg, basestring):
        if is_identifier(arg, dotted=True):
            # The string is a single identifier.  Check directly whether it
            # needs import.  This is an optimization to not bother parsing an
            # AST.
            if symbol_needs_import(arg, namespaces):
                return [arg]
            else:
                return []
        else:
            # Parse the string as code.
            arg = ast.parse(arg) # may raise SyntaxError
            # Fall through.
    if not isinstance(arg, ast.AST):
        raise TypeError(
            "find_missing_imports(): expected a string of AST node; got a %s"
            % (type(arg).__name__,))
    # Traverse the abstract syntax tree.
    if debugging_enabled:
        debug("ast=%s", ast.dump(arg))
    visitor = _MissingImportFinder(namespaces=namespaces)
    visitor.visit(arg)
    return sorted(visitor.missing_imports)


@memoize
def is_importable(fullname):
    """
    Return whether C{fullname} is expected to be an importable module.

      >>> is_importable("pkgutil")
      True

      >>> is_importable("asdfasdf")
      False

    The result is cached.

    @type fullname:
      C{str}
    @param fullname:
      Fully-qualified module name, e.g. "sqlalchemy.orm".
    @rtype:
      C{bool}
    """
    if fullname in sys.modules:
        # If it's already been imported, then it's obviously importable.
        return True
    if '.' in fullname:
        # First check if prefix component is importable.
        prefix = fullname.rsplit(".", 1)[0]
        if not is_importable(prefix):
            return False
    import pkgutil
    if pkgutil.find_loader(fullname) is not None:
        # If pkgutil finds a loader for it then it's expected to be
        # importable.
        return True
    elif "." in fullname:
        # pkgutil has false-negatives for non-top-level modules -- it doesn't
        # find all importable things.  Try to import it.
        try:
            __import__(fullname)
            return True
        except Exception as e:
            debug("%r is not importable: %s: %s", fullname, type(e).__name__, e)
    return False


def get_known_import(fullname):
    """
    Get the deepest known import.

    For example, suppose:
      - The user accessed "foo.bar.baz",
      - We know imports for "foo", "foo.bar", and "foo.bar.quux".

    Then we return "import foo.bar".

    @type fullname:
      C{str}
    @param fullname:
      Fully-qualified name, such as "scipy.interpolate"
    """
    # Get the global import database.  This loads on first use and is
    # cached thereafter.
    from pyflyby.importdb import global_known_imports
    db = global_known_imports()

    # Look for the "deepest" import we know about.  Suppose the user
    # accessed "foo.bar.baz".  If we have an auto-import for "foo.bar",
    # then import that.  (Presumably, the auto-import for "foo", if it
    # exists, refers to the same foo.)
    for partial_name in dotted_prefixes(fullname, reverse=True):
        try:
            result = db.by_fullname_or_import_as[partial_name]
            debug("get_known_import(%r): found %r", fullname, result)
            return result
        except KeyError:
            debug("get_known_import(%r): no known import for %r", fullname, partial_name)
            pass
    debug("get_known_import(%r): found nothing", fullname)
    return None


_IMPORT_FAILED = set()
"""
Set of imports we've already attempted and failed.
"""

def _try_import(imp, namespace):
    """
    Try to execute an import.  Import the result into the namespace
    C{namespace}.

    Print to stdout what we're about to do.

    Only import into C{namespace} if we won't clobber an existing definition.

    @type imp:
      C{pyflyby.importstmt.Import} or C{str}
    @param imp:
      The import to execute, e.g. "from numpy import arange"
    @type namespace:
      C{dict}
    @param namespace:
      Namespace to import into.
    @return:
      C{True} on success, C{False} on failure
    """
    # TODO: generalize "imp" to any python statement whose toplevel is a
    # single Store (most importantly import and assignment, but could also
    # include def & cdef).  For things other than imports, we would want to
    # first run handle_auto_imports() on the code.
    from pyflyby.importstmt import Import
    imp = Import(imp)
    if imp in _IMPORT_FAILED:
        debug("Not attempting previously failed %r", imp)
        return False
    impas = imp.import_as
    name0 = impas.split(".", 1)[0]
    stmt = str(imp)
    info(stmt)
    # Do the import in a temporary namespace, then copy it to C{namespace}
    # manually.  We do this instead of just importing directly into
    # C{namespace} for the following reason: Suppose the user wants "foo.bar",
    # but "foo" already exists in the global namespace.  In order to import
    # "foo.bar" we need to import its parent module "foo".  We only want to do
    # the "foo.bar" import if what we import as "foo" is the same as the
    # preexisting "foo".  OTOH, we _don't_ want to do the "foo.bar" import if
    # the user had for some reason done "import fool as foo".  So we (1)
    # import into a scratch namespace, (2) check that the top-level matches,
    # then (3) copy into the user's namespace if it didn't already exist.
    scratch_namespace = {}
    try:
        exec stmt in scratch_namespace
        imported = scratch_namespace[name0]
    except Exception as e:
        info("Error attempting to %r: %s: %s", stmt, type(e).__name__, e)
        _IMPORT_FAILED.add(imp)
        return False
    try:
        preexisting = namespace[name0]
    except KeyError:
        # The top-level symbol didn't previously exist in the user's global
        # namespace.  Add it.
        namespace[name0] = imported
    else:
        # The top-level symbol already existed in the user's global namespace.
        # Check that it matched.
        if preexisting is not imported:
            info("  => Failed: pre-existing %r (%r) differs from imported %r",
                 name0, preexisting, name0)
            return False
    return True


def auto_import_symbol(fullname, namespaces=None):
    """
    Try to auto-import a single name.

    @type fullname:
      C{str}
    @param fullname:
      Fully-qualified module name, e.g. "sqlalchemy.orm".
    @type namespaces:
      C{list} of C{dict}, e.g. [globals()].
    @param namespaces:
      Namespaces to check.  Namespace[-1] is the namespace to import into.
    """
    namespaces = interpret_namespaces(namespaces)
    if not symbol_needs_import(fullname, namespaces):
        return
    # See whether there's a known import for this name.  This is mainly
    # important for things like "from numpy import arange".  Imports such as
    # "import sqlalchemy.orm" will also be handled by this, although it's less
    # important, since we're going to attempt that import anyway if it looks
    # like a "sqlalchemy" package is importable.
    imports = get_known_import(fullname)
    if imports is None:
        # No known imports.
        pass
    else:
        assert len(imports) >= 1
        if len(imports) > 1:
            # Doh, multiple imports.
            info("Multiple candidate imports for %s ; please pick one:", fullname)
            for imp in imports:
                info("  %s", imp)
            return
        imp, = imports
        if symbol_needs_import(imp.import_as, namespaces=namespaces):
            # We're ready for some real action.  The input code references a
            # name/attribute that (a) is not locally assigned, (b) is not a
            # global, (c) is not yet imported, (d) is a known auto-import, (e)
            # has only one definition
            # TODO: label which known_imports file the autoimport came from
            if not _try_import(imp, namespaces[-1]):
                # Failed; don't do anything else.
                return
            # Succeeded.
            if imp.import_as == fullname:
                # We got what we wanted, so nothing more to do.
                return
            if imp.import_as != imp.fullname:
                # This is not just an 'import foo.bar'; rather, it's a 'import
                # foo.bar as baz' or 'from foo import bar'.  So don't go any
                # further.
                return
        # Fall through.
    # We haven't yet imported what we want.  Either there was no entry in the
    # known imports database, or it wasn't "complete" (e.g. the user wanted
    # "foo.bar.baz", and the known imports database only knew about "import
    # foo.bar").  For each component that may need importing, check if the
    # loader thinks it should be importable, and if so import it.
    for pname in dotted_prefixes(fullname):
        if not symbol_needs_import(pname, namespaces):
            continue
        if not is_importable(pname):
            debug("auto_import_symbol(%r): %r is not importable", fullname, pname)
            return
        if not _try_import("import %s" % pname, namespaces[-1]):
            return


def auto_import(arg, namespaces=None):
    """
    Parse C{arg} for symbols that need to be imported and automatically import
    them.

    @type arg:
      C{str} or C{ast.AST}
    @param arg:
      Python code text (as simple as a single qualified name, or as complex as
      an entire module text) or an AST node
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Namespaces to check.  Namespace[-1] is the namespace to import into.
    """
    namespaces = interpret_namespaces(namespaces)
    try:
        fullnames = find_missing_imports(arg, namespaces)
    except SyntaxError:
        debug("syntax error parsing %r", arg)
        return
    debug("Missing imports: %r", fullnames)
    for fullname in fullnames:
        auto_import_symbol(fullname, namespaces)


def load_symbol(fullname, namespaces=None, autoimport=False):
    """
    Load the symbol C{fullname}.

      >>> load_symbol("os.path.join.func_name", {"os": os})
      'join'

      >>> load_symbol("os.path.join.asdf", {"os": os})
      Traceback (most recent call last):
        ...
      AttributeError: 'function' object has no attribute 'asdf'

      >>> load_symbol("os.path.join", {})
      Traceback (most recent call last):
        ...
      AttributeError: os

    @type fullname:
      C{str}
    @param fullname:
      Fully-qualified symbol name, e.g. "os.path.join".
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Namespaces to check.
    @param autoimport:
      If C{False} (default), the symbol must already be imported.
      If C{True}, then auto-import the symbol first.
    @return:
      Object.
    @raise AttributeError:
      Object was not found.
    """
    namespaces = interpret_namespaces(namespaces)
    if autoimport:
        # Auto-import the symbol first.
        # We do the lookup as a separate step after auto-import.  (An
        # alternative design could be to have auto_import_symbol() return the
        # symbol if possible.  We don't do that because most users of
        # auto_import_symbol() don't need to follow down arbitrary (possibly
        # non-module) attributes.)
        auto_import_symbol(fullname, namespaces)
    name_parts = fullname.split(".")
    name0 = name_parts[0]
    for namespace in namespaces:
        try:
            obj = namespace[name0]
        except KeyError:
            pass
        else:
            for n in name_parts[1:]:
                obj = getattr(obj, n) # may raise AttributeError
            return obj
    else:
        raise AttributeError(name0) # not found in any namespace


@memoize
def _list_submodules(module):
    """
    Enumerate the importable submodules of package C{fullname}.

      >>> import numpy
      >>> _list_submodules(numpy)                   # doctest:+ELLIPSIS
      (..., 'random', ..., 'version')

    @type module:
      C{ModuleType}
    @param module:
      Package whose (sub)modules we should enumerate.  If C{None}, enumerate
      top-level importable modules.
    @rtype:
      C{tuple} of C{str}
    """
    import pkgutil
    if module is None:
        modlist = pkgutil.iter_modules(None)
    elif isinstance(module, types.ModuleType):
        try:
            path = module.__path__
        except AttributeError:
            return []
        modlist = pkgutil.iter_modules(path)
    else:
        raise TypeError(
            "_list_submodules(): expected a module but got a %s"
            % (type(module).__name__,))
    module_names = [t[1] for t in modlist]
    return tuple(sorted(set(module_names)))


def _list_members_for_completion(obj):
    """
    Enumerate the existing member attributes of an object.
    This emulates the regular Python/IPython completion items.

    It does not include not-yet-imported submodules.

    @param obj:
      Object whose member attributes to enumerate.
    @rtype:
      C{list} of C{str}
    """
    ip = get_ipython_safe()
    if ip is None:
        words = dir(obj)
    else:
        from IPython.utils import generics
        from IPython.utils.dir2 import dir2
        from IPython.core.error import TryNext
        if ip.Completer.limit_to__all__ and hasattr(obj, '__all__'):
            try:
                words = getattr(obj, '__all__')
            except:
                return []
        else:
            words = dir2(obj)
            try:
                words = generics.complete_object(obj, words)
            except TryNext:
                pass
    return [w for w in words if isinstance(w, basestring)]


def complete_symbol(fullname, namespaces=None):
    """
    Enumerate possible completions for C{fullname}.

    Includes globals and auto-importable symbols.

      >>> complete_symbol("nump")                   # doctest:+ELLIPSIS
      [...'numpy'...]

    Completion works on attributes, even on modules not yet imported - modules
    are auto-imported first if not yet imported:

      >>> ns = {}
      >>> complete_symbol("numpy.aran", namespaces=[ns])
      [AUTOIMPORT] import numpy
      ['numpy.arange']

      >>> 'numpy' in ns
      True

      >>> complete_symbol("numpy.aran", namespaces=[ns])
      ['numpy.arange']

    We only need to import *parent* modules (packages) of the symbol being
    completed.  If the user asks to complete "foo.bar.quu<TAB>", we need to
    import foo.bar, but we don't need to import foo.bar.quux.

    @type fullname:
      C{str}
    @param fullname:
      String to complete.  ("Full" refers to the fact that it should contain
      dots starting from global level.)
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Namespaces of (already-imported) globals.
    @rtype:
      C{list} of C{str}
    @return:
      Completion candidates.
    """
    namespaces = interpret_namespaces(namespaces)
    debug("complete_symbol(%r)", fullname)
    # Require that the input be a prefix of a valid symbol.
    if not is_identifier(fullname, dotted=True, prefix=True):
        return []
    # Get the database of known imports.
    from pyflyby.importdb import global_known_imports
    db = global_known_imports()
    if '.' not in fullname:
        # Check global names, including global-level known modules and
        # importable modules.
        results = set()
        for ns in namespaces:
            for name in ns:
                if '.' not in name:
                    results.add(name)
        results.update(db.member_names.get("", []))
        results.update(_list_submodules(None))
        assert all('.' not in r for r in results)
        results = sorted([r for r in results if r.startswith(fullname)])
    else:
        # Check members, including known sub-modules and importable sub-modules.
        splt = fullname.rsplit(".", 1)
        pname, attrname = splt
        try:
            parent = load_symbol(pname, namespaces, autoimport=True)
        except AttributeError:
            # Even after attempting auto-import, the symbol is still
            # unavailable.  Nothing to complete.
            debug("complete_symbol(%r): couldn't load symbol %r", fullname, pname)
            return []
        results = set()
        results.update(_list_members_for_completion(parent))
        if sys.modules.get(pname, object()) is parent and parent.__name__ == pname:
            results.update(db.member_names.get(pname, []))
            results.update(_list_submodules(parent))
        results = sorted([r for r in results if r.startswith(attrname)])
        results = ["%s.%s" % (pname, r) for r in results]
    return results


def _complete_symbol_during_prompt(fullname):
    with InterceptPrintsDuringPromptCtx():
        return complete_symbol(fullname)



class _AutoImporter_ast_transformer(object):
    """
    A NodeVisitor-like wrapper around C{auto_import_for_ast} for the API that
    IPython 1.x's C{ast_transformers} needs.
    """

    def visit(self, node):
        try:
            # We don't actually transform the node; we just use the
            # ast_transformers mechanism instead of the prefilter mechanism as
            # an optimization to avoid re-parsing the text into an AST.
            auto_import(node)
            return node
        except:
            import traceback
            traceback.print_exc()
            raise


class _AutoImporter_prefilter_checker(object):
    """
    A prefilter checker for IPython < 1.0.
    """
    priority = 1
    enabled = True

    def check(self, line_info):
        debug("prefilter %r", line_info.line)
        auto_import(line_info.line)
        return None



@memoize
def install_auto_importer():
    """
    Install the auto-importer into IPython.
    """
    ip = get_ipython_safe()
    if not ip:
        return
    import IPython
    debug("Initializing pyflyby auto importer for IPython version %s", IPython.__version__)

    # Install a pre-code-execution hook.
    #
    # There are a few different places within IPython we can consider hooking:
    #   * ip.input_transformer_manager.logical_line_transforms
    #   * ip.prefilter_manager.checks
    #   * ip.ast_transformers
    #   * ip.hooks['pre_run_code_hook']
    #   * ip._ofind
    #
    # We choose to hook in two places: (1) _ofind and (2) ast_transformers.
    # The motivation follows.  We want to handle auto-imports for all of these
    # input cases:
    #   (1) "foo.bar"
    #   (2) "arbitrarily_complicated_stuff((lambda: foo.bar)())"
    #   (3) "foo.bar?", "foo.bar??" (pinfo/pinfo2)
    #   (4) "foo.bar 1, 2" => "foo.bar(1, 2)" (autocall)
    #
    # Case 1 is the easiest and can be handled by nearly any method.  Case 2
    # must be done either as a prefilter or as an AST transformer.  Cases 3
    # and 4 must be done either as an input line transformer or by
    # monkey-patching _ofind, because by the time the
    # prefilter/ast_transformer is called, it's too late.
    #
    # To handle case 2, we use an AST transformer or prefilter.
    #
    # To handle cases 3/4 (pinfo/autocall), we choose to hook _ofind.  This is
    # a private function that is called by both pinfo and autocall code paths.
    # (Alternatively, we could have added something to the
    # logical_line_transforms.  The downside of that is that we would need to
    # re-implement all the parsing perfectly matching IPython.  Although
    # monkey-patching is in general bad, it seems the seems the lesser of the
    # two evils in this case.)
    #
    # Since we have two invocations of handle_auto_imports(), case 1 is
    # handled twice.  That's fine because it runs quickly.

    # Hook _ofind.
    if hasattr(ip, "_ofind"):
        orig_ofind = ip._ofind
        def wrapped_ofind(oname, namespaces=None):
            debug("_ofind(oname=%r, namespaces=%r)", oname, namespaces)
            if namespaces is None:
                namespaces = _ipython_namespaces(ip)
            if is_identifier(oname, dotted=True):
                auto_import(str(oname), [ns for nsname,ns in namespaces][::-1])
            result = orig_ofind(oname, namespaces=namespaces)
            return result
        ip._ofind = wrapped_ofind
    else:
        debug("Couldn't install ofind hook for IPython version %s", IPython.__version__)

    if hasattr(ip, 'ast_transformers'):
        # IPython >= 1.0+: Hook ast_transformers.
        ip.ast_transformers.append(_AutoImporter_ast_transformer())
    elif hasattr(ip, 'prefilter_manager'):
        # IPython < 1.0: Add prefilter manager.
        ip.prefilter_manager.register_checker(_AutoImporter_prefilter_checker())
    else:
        debug("Couldn't install a line transformer for IPython version %s", IPython.__version__)

    # Install a tab-completion hook.
    #
    # There are a few different places within IPython we can consider hooking:
    #   * ip.completer.custom_completers / ip.set_hook("complete_command")
    #   * ip.completer.python_matches
    #   * ip.completer.global_matches
    #   * ip.completer.attr_matches
    #   * ip.completer.python_func_kw_matches
    #
    # The "custom_completers" list, which set_hook("complete_command")
    # manages, is not useful because that only works for specific commands.
    # (A "command" refers to the first word on a line, such as "cd".)
    #
    # We choose to hook global_matches() and attr_matches(), which are called
    # to enumerate global and non-global attribute symbols respectively.
    # (python_matches() calls these two.  We hook global_matches() and
    # attr_matches() instead of python_matches() because a few other functions
    # call global_matches/attr_matches directly.)
    #
    if hasattr(ip, "Completer"):
        completer = ip.Completer
        completer.global_matches = _complete_symbol_during_prompt
        completer.attr_matches   = _complete_symbol_during_prompt
        # TODO: also hook completer.python_func_kw_matches
    else:
        debug("Couldn't install completion hook for IPython version %s", IPython.__version__)
