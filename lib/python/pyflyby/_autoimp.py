# pyflyby/_autoimp.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __builtin__
import ast
import contextlib
import copy
import os
import types

from   pyflyby._file            import FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._idents          import DottedIdentifier, is_identifier
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import Import
from   pyflyby._log             import logger
from   pyflyby._modules         import ModuleHandle
from   pyflyby._parse           import PythonBlock, infer_compile_mode


class _ClassScope(dict):
    pass


class ScopeStack(tuple):
    """
    A stack of namespace scopes, as a tuple of C{dict}s.

    Each entry is a C{dict}.

    Ordered from most-global to most-local.
    Builtins are always included.
    Duplicates are removed.
    """

    def __new__(cls, arg):
        """
        Interpret argument as a C{ScopeStack}.

        @type arg:
          C{ScopeStack}, C{dict}, C{list} of C{dict}
        @param arg:
          Input namespaces
        @rtype:
          C{ScopeStack}
        """
        if isinstance(arg, ScopeStack):
            return arg
        if isinstance(arg, dict):
            scopes = [arg]
        elif isinstance(arg, (tuple, list)):
            scopes = list(arg)
        else:
            raise TypeError(
                "ScopeStack: expected a sequence of dicts; got a %s"
                % (type(arg).__name__,))
        if not len(scopes):
            raise TypeError("ScopeStack: no scopes given")
        if not all(isinstance(scope, dict) for scope in scopes):
            raise TypeError("Expected list of dicts; got a sequence of %r"
                            % ([type(x).__name__ for x in scopes]))
        scopes = [__builtin__.__dict__] + scopes
        result = []
        seen = set()
        # Keep only unique items, checking uniqueness by object identity.
        for scope in scopes:
            if id(scope) in seen:
                continue
            seen.add(id(scope))
            result.append(scope)
        self = tuple.__new__(cls, result)
        return self

    def with_new_scope(self, include_class_scopes=False, new_class_scope=False):
        """
        Return a new C{ScopeStack} with an additional empty scope.

        @param include_class_scopes:
          Whether to include previous scopes that are meant for ClassDefs.
        @param new_class_scope:
          Whether the new scope is for a ClassDef.
        @rtype:
          C{ScopeStack}
        """
        if include_class_scopes:
            scopes = tuple(self)
        else:
            scopes = tuple(s for s in self
                           if not isinstance(s, _ClassScope))
        if new_class_scope:
            new_scope = _ClassScope()
        else:
            new_scope = {}
        cls = type(self)
        result = tuple.__new__(cls, scopes + (new_scope,))
        return result

    def clone_top(self):
        """
        Return a new C{ScopeStack} referencing the same namespaces as C{self},
        but cloning the topmost namespace (and aliasing the others).
        """
        scopes = list(self)
        scopes[-1] = copy.copy(scopes[-1])
        cls = type(self)
        return tuple.__new__(cls, scopes)


def symbol_needs_import(fullname, namespaces):
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
      C{DottedIdentifier}
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
    namespaces = ScopeStack(namespaces)
    fullname = DottedIdentifier(fullname)
    partial_names = fullname.prefixes[::-1]
    # Iterate over local scopes.
    for ns_idx, ns in enumerate(namespaces):
        # Iterate over partial names: "foo.bar.baz.quux", "foo.bar.baz", ...
        for partial_name in partial_names:
            # Check if this partial name was imported/assigned in this
            # scope.  In the common case, there will only be one namespace
            # in the namespace stack, i.e. the user globals.
            try:
                var = ns[str(partial_name)]
            except KeyError:
                continue
            # Suppose the user accessed fullname="foo.bar.baz.quux" and
            # suppose we see "foo.bar" was imported (or otherwise assigned) in
            # the scope vars (most commonly this means it was imported
            # globally).  Let's check if foo.bar already has a "baz".
            prefix_len = len(partial_name.parts)
            suffix_parts = fullname.parts[prefix_len:]
            pname = str(partial_name)
            for part in suffix_parts:
                if not isinstance(var, types.ModuleType):
                    # The variable is not a module.  (If this came from a
                    # local assignment then C{var} will just be "None"
                    # here to indicate we know it was assigned but don't
                    # know about its type.)  Thus nothing under it needs
                    # import.
                    logger.debug("symbol_needs_import(%r): %s is in namespace %d (under %r) and not a module, so it doesn't need import", fullname, pname, ns_idx, partial_name)
                    return False
                try:
                    var = getattr(var, part)
                except AttributeError:
                    # We saw that "foo.bar" is imported, and is a module,
                    # but it does not have a "baz" attribute.  Thus, as we
                    # know so far, foo.bar.baz requires import.  But
                    # continue on to the next scope.
                    logger.debug("symbol_needs_import(%r): %s is a module in namespace %d (under %r), but has no %r attribute", fullname, pname, ns_idx, partial_name, part)
                    break # continue outer loop
                pname = "%s.%s" % (pname, part)
            else:
                # We saw that "foo.bar" is imported, and checked that
                # foo.bar has an attribute "baz", which has an
                # attribute "quux" - so foo.bar.baz.quux does not need
                # to be imported.
                assert pname == str(fullname)
                logger.debug("symbol_needs_import(%r): found it in namespace %d (under %r), so it doesn't need import", fullname, ns_idx, partial_name)
                return False
    # We didn't find any scope that defined the name.  Therefore it needs
    # import.
    logger.debug("symbol_needs_import(%r): no match found in namespaces; it needs import", fullname)
    return True


class _MissingImportFinder(ast.NodeVisitor):
    """
    A helper class to be used only by L{_find_missing_imports_in_ast}.

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

    def __init__(self, scopestack):
        """
        Construct the AST visitor.

        @type scopestack:
          L{ScopeStack}
        @param scopestack:
          Initial scope stack.
        """
        # Create a stack of namespaces.  The caller should pass in a list that
        # includes the globals dictionary.  ScopeStack() will make sure this
        # includes builtins.
        scopestack = ScopeStack(scopestack)
        # Add an empty namespace to the stack.  This facilitates adding stuff
        # to scopestack[-1] without ever modifying user globals.
        scopestack = scopestack.with_new_scope()
        self.scopestack = scopestack
        # Create data structure to hold the result.
        self.missing_imports = set()
        # Function bodies that we need to check after defining names in this
        # function scope.
        self._deferred_load_checks = []
        # Whether we're currently in a FunctionDef.
        self._in_FunctionDef = False

    def find_missing_imports(self, node):
        self.visit(node)
        self._finish_deferred_load_checks()
        return sorted(self.missing_imports)

    @contextlib.contextmanager
    def _NewScopeCtx(self, **kwargs):
        """
        Context manager that temporarily pushes a new empty namespace onto the
        stack of namespaces.
        """
        prev_scopestack = self.scopestack
        new_scopestack = prev_scopestack.with_new_scope(**kwargs)
        self.scopestack = new_scopestack
        try:
            yield
        finally:
            assert self.scopestack is new_scopestack
            self.scopestack = prev_scopestack

    def visit_Lambda(self, node):
        with self._NewScopeCtx():
            self.generic_visit(node)

    def visit_ClassDef(self, node):
        for base in node.bases:
            self.visit(base)
        for decorator in node.decorator_list:
            self.visit(decorator)
        with self._NewScopeCtx(new_class_scope=True):
            for child in node.body:
                self.visit(child)
        # The class's name is only visible to others (not to the body to the
        # class).
        self._visit_Store(node.name)

    def visit_FunctionDef(self, node):
        self._visit_Store(node.name)
        old_in_FunctionDef = self._in_FunctionDef
        self._in_FunctionDef = True
        with self._NewScopeCtx():
            self.generic_visit(node)
        self._in_FunctionDef = old_in_FunctionDef

    def visit_arguments(self, node):
        self._visit_Store(node.vararg)
        self._visit_Store(node.kwarg)
        self.generic_visit(node)

    def visit_comprehension(self, node):
        # Visit a "comprehension" node, which is a component of list
        # comprehensions and generator expressions.
        self.visit(node.iter)
        def visit_target(target):
            if isinstance(target, ast.Name):
                self._visit_Store(target.id)
            elif isinstance(target, (ast.Tuple, ast.List)):
                for elt in target.elts:
                    visit_target(elt)
            else:
                raise AssertionError(
                    "unexpected %s in comprehension" % (type(target).__name__))
        visit_target(node.target)
        for n in node.ifs:
            self.visit(n)

    def visit_ListComp(self, node):
        # Visit a list comprehension node.
        # This is basically the same as the generic visit, except that we
        # visit the comprehension node(s) before the elt node.
        # (generic_visit() would visit the elt first, because that comes first
        # in ListComp._fields).
        # We intentionally don't enter a new scope here, because a list
        # comprehensive _does_ leak variables out of its scope (unlike
        # generator expressions).
        for comprehension in node.generators:
            self.visit(comprehension)
        self.visit(node.elt)

    def visit_GeneratorExp(self, node):
        # Visit a generator expression node.
        # This is just like a ListComp, except that we enter a new scope,
        # because a generator expression does _not_ leak variables out of its
        # scope (unlike list comprehensions).
        with self._NewScopeCtx(include_class_scopes=True):
            self.visit_ListComp(node)

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
        logger.debug("visit_Name(%r)", node.id)
        self._visit_fullname(node.id, node.ctx)

    def visit_Attribute(self, node):
        logger.debug("visit_Attribute(%r)", node.attr)
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
        logger.debug("_visit_Store(%r)", fullname)
        self.scopestack[-1][fullname] = None

    def _visit_Load(self, fullname):
        logger.debug("_visit_Load(%r)", fullname)
        if self._in_FunctionDef:
            # We're in a FunctionDef.  We need to defer checking whether this
            # references undefined names.  The reason is that globals (or
            # stores in a parent function scope) may be stored later.
            # For example, bar() is defined later after the body of foo(), but
            # still available to foo() when it is called:
            #    def foo():
            #        return bar()
            #    def bar():
            #        return 42
            #    foo()
            # To support this, we clone the top of the scope stack and alias
            # the other scopes in the stack.  Later stores in the same scope
            # shouldn't count, e.g. x should be considered undefined in the
            # following example:
            #    def foo():
            #        print x
            #        x = 1
            # On the other hand, we intentionally alias the other scopes
            # rather than cloning them, because the point is to allow them to
            # be modified until we do the check at the end.
            data = (fullname, self.scopestack.clone_top())
            self._deferred_load_checks.append(data)
        else:
            # We're not in a FunctionDef.  Deferring would give us the same
            # result; we do the check now to avoid the overhead of cloning the
            # stack.
            self._check_load(fullname, self.scopestack)

    def _check_load(self, fullname, scopestack):
        if symbol_needs_import(fullname, scopestack):
            self.missing_imports.add(fullname)

    def _finish_deferred_load_checks(self):
        for fullname, scopestack in self._deferred_load_checks:
            self._check_load(fullname, scopestack)
        self._deferred_load_checks = []



def _find_missing_imports_in_ast(node, namespaces):
    """
    Find missing imports in an AST node.
    Helper function to L{find_missing_imports}.

      >>> node = ast.parse("import numpy; numpy.arange(x) + arange(x)")
      >>> _find_missing_imports_in_ast(node, [{}])
      ['arange', 'x']

    @type node:
      C{ast.AST}
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @rtype:
      C{list} of C{str}
    """
    if not isinstance(node, ast.AST):
        raise TypeError
    # Traverse the abstract syntax tree.
    if logger.debug_enabled:
        logger.debug("ast=%s", ast.dump(node))
    return _MissingImportFinder(namespaces).find_missing_imports(node)

# TODO: maybe we should replace _find_missing_imports_in_ast with
# _find_missing_imports_in_code(compile(node)).  The method of parsing opcodes
# is simpler, because Python takes care of the scoping issue for us and we
# don't have to worry about locals.  It does, however, depend on CPython
# implementation details, whereas the AST is well-defined by the language.


def _find_missing_imports_in_code(co, namespaces):
    """
    Find missing imports in a code object.
    Helper function to L{find_missing_imports}.

      >>> f = lambda: foo.bar(x) + baz(y)
      >>> _find_missing_imports_in_code(f.func_code, [{}])
      ['baz', 'foo.bar', 'x', 'y']

      >>> f = lambda x: (lambda: x+y)
      >>> _find_missing_imports_in_code(f.func_code, [{}])
      ['y']

    @type co:
      C{types.CodeType}
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @rtype:
      C{list} of C{str}
    """
    loads_without_stores = set()
    _find_loads_without_stores_in_code(co, loads_without_stores)
    missing_imports = [
        fullname for fullname in sorted(loads_without_stores)
        if symbol_needs_import(fullname, namespaces)
        ]
    return missing_imports


def _find_loads_without_stores_in_code(co, loads_without_stores):
    """
    Find global LOADs without corresponding STOREs, by disassembling code.
    Recursive helper for L{_find_missing_imports_in_code}.

    @type co:
      C{types.CodeType}
    @param co:
      Code object, e.g. C{function.func_code}
    @type loads_without_stores:
      C{set}
    @param loads_without_stores:
      Mutable set to which we add loads without stores.
    @return:
      C{None}
    """
    if not isinstance(co, types.CodeType):
        raise TypeError(
            "_find_loads_without_stores_in_code(): expected a CodeType; got a %s"
            % (type(co).__name__,))
    # Initialize local constants for fast access.
    from opcode import HAVE_ARGUMENT, EXTENDED_ARG, opmap
    LOAD_ATTR    = opmap['LOAD_ATTR']
    LOAD_GLOBAL  = opmap['LOAD_GLOBAL']
    LOAD_NAME    = opmap['LOAD_NAME']
    STORE_ATTR   = opmap['STORE_ATTR']
    STORE_GLOBAL = opmap['STORE_GLOBAL']
    STORE_NAME   = opmap['STORE_NAME']
    # Keep track of the partial name so far that started with a LOAD_GLOBAL.
    # If C{pending} is not None, then it is a list representing the name
    # components we've seen so far.
    pending = None
    # Disassemble the code.  Look for LOADs and STOREs.  This code is based on
    # C{dis.disassemble}.
    #
    # Scenarios:
    #
    #   * Function-level load a toplevel global
    #         def f():
    #             aa
    #         => LOAD_GLOBAL; other (not LOAD_ATTR or STORE_ATTR)
    #   * Function-level load an attribute of global
    #         def f():
    #             aa.bb.cc
    #         => LOAD_GLOBAL; LOAD_ATTR; LOAD_ATTR; other
    #   * Function-level store a toplevel global
    #         def f():
    #             global aa
    #             aa = 42
    #         => STORE_GLOBAL
    #   * Function-level store an attribute of global
    #         def f():
    #             aa.bb.cc = 42
    #         => LOAD_GLOBAL, LOAD_ATTR, STORE_ATTR
    #   * Function-level load a local
    #         def f():
    #             aa = 42
    #             return aa
    #         => LOAD_FAST or LOAD_NAME
    #   * Function-level store a local
    #         def f():
    #             aa = 42
    #         => STORE_FAST or STORE_NAME
    #   * Function-level load an attribute of a local
    #         def f():
    #             aa = 42
    #             return aa.bb.cc
    #         => LOAD_FAST; LOAD_ATTR; LOAD_ATTR
    #   * Function-level store an attribute of a local
    #         def f():
    #             aa == 42
    #             aa.bb.cc = 99
    #         => LOAD_FAST; LOAD_ATTR; STORE_ATTR
    #   * Function-level load an attribute of an expression other than a name
    #         def f():
    #             foo().bb.cc
    #         => [CALL_FUNCTION, etc]; LOAD_ATTR; LOAD_ATTR
    #   * Function-level store an attribute of an expression other than a name
    #         def f():
    #             foo().bb.cc = 42
    #         => [CALL_FUNCTION, etc]; LOAD_ATTR; STORE_ATTR
    #   * Function-level import
    #         def f():
    #             import aa.bb.cc
    #         => IMPORT_NAME "aa.bb.cc", STORE_FAST "aa"
    #   * Module-level load of a top-level global
    #         aa
    #         => LOAD_NAME
    #   * Module-level store of a top-level global
    #         aa = 42
    #         => STORE_NAME
    #   * Module-level load of an attribute of a global
    #         aa.bb.cc
    #         => LOAD_NAME, LOAD_ATTR, LOAD_ATTR
    #   * Module-level store of an attribute of a global
    #         aa.bb.cc = 42
    #         => LOAD_NAME, LOAD_ATTR, STORE_ATTR
    #   * Module-level import
    #         import aa.bb.cc
    #         IMPORT_NAME "aa.bb.cc", STORE_NAME "aa"
    #   * Closure
    #         def f():
    #             aa = 42
    #             return lambda: aa
    #         f: STORE_DEREF, LOAD_CLOSURE, MAKE_CLOSURE
    #         g = f(): LOAD_DEREF
    bytecode = co.co_code
    n = len(bytecode)
    i = 0
    extended_arg = 0
    stores = set()
    loads_after_label = set()
    loads_before_label_without_stores = set()
    # Find the earliest target of a backward jump.
    earliest_backjump_label = _find_earliest_backjump_label(bytecode)
    # Loop through bytecode.
    while i < n:
        c = bytecode[i]
        op = ord(c)
        i += 1
        if op >= HAVE_ARGUMENT:
            oparg = ord(bytecode[i]) + ord(bytecode[i+1])*256 + extended_arg
            extended_arg = 0
            i = i+2
            if op == EXTENDED_ARG:
                extended_arg = oparg*65536L
                continue

        if pending is not None:
            if op == STORE_ATTR:
                # {LOAD_GLOBAL|LOAD_NAME} {LOAD_ATTR}* {STORE_ATTR}
                pending.append(co.co_names[oparg])
                fullname = ".".join(pending)
                pending = None
                stores.add(fullname)
                continue
            if op == LOAD_ATTR:
                # {LOAD_GLOBAL|LOAD_NAME} {LOAD_ATTR}* so far;
                # possibly more LOAD_ATTR/STORE_ATTR will follow
                pending.append(co.co_names[oparg])
                continue
            # {LOAD_GLOBAL|LOAD_NAME} {LOAD_ATTR}* (and no more
            # LOAD_ATTR/STORE_ATTR)
            fullname = ".".join(pending)
            pending = None
            if i >= earliest_backjump_label:
                loads_after_label.add(fullname)
            elif fullname not in stores:
                loads_before_label_without_stores.add(fullname)
            # Fall through.

        if op in [LOAD_GLOBAL, LOAD_NAME]:
            pending = [co.co_names[oparg]]
            continue

        if op in [STORE_GLOBAL, STORE_NAME]:
            stores.add(co.co_names[oparg])
            continue

        # We don't need to worry about: LOAD_FAST, STORE_FAST, LOAD_CLOSURE,
        # LOAD_DEREF, STORE_DEREF.  LOAD_FAST and STORE_FAST refer to local
        # variables; LOAD_CLOSURE, LOAD_DEREF, and STORE_DEREF relate to
        # closure variables.  In both cases we know these are not missing
        # imports.  It's convenient that these are separate opcodes, because
        # then we don't need to deal with them manually.

    # Record which variables we saw that were loaded in this module without a
    # corresponding store.  We handle two cases.
    #
    #   1. Load-before-store; no loops (i.e. no backward jumps).
    #      Example A::
    #          foo.bar()
    #          import foo
    #      In the above example A, "foo" was used before it was imported.  We
    #      consider it a candidate for auto-import.
    #      Example B:
    #          if condition1():         # L1
    #             import foo1           # L2
    #          foo1.bar() + foo2.bar()  # L3
    #          import foo2              # L4
    #      In the above example B, "foo2" was used before it was imported; the
    #      fact that there is a jump target at L3 is irrelevant because it is
    #      the target of a forward jump; there is no way that foo2 can be
    #      imported (L4) before foo2 is used (L3).
    #      On the other hand, we don't know whether condition1 will be true,
    #      so we assume L2 will be executed and therefore don't consider the
    #      use of "foo1" at L3 to be problematic.
    #
    #   2. Load-before-store; with loops (backward jumps).  Example:
    #         for i in range(10):
    #            if i > 0:
    #                print x
    #            else:
    #                x = "hello"
    #       In the above example, "x" is actually always stored before load,
    #       even though in a linear reading of the bytecode we would see the
    #       store before any loads.
    #
    # It would be impossible to perfectly follow conditional code, because
    # code could be arbitrarily complicated and would require a flow control
    # analysis that solves the halting problem.  We do the best we can and
    # handle case 1 as a common case.
    #
    # Case 1: If we haven't seen a label, then we know that any load
    #         before a preceding store is definitely too early.
    # Case 2: If we have seen a label, then we consider any preceding
    #         or subsequent store to potentially match the load.
    loads_without_stores.update( loads_before_label_without_stores ) # case 1
    loads_without_stores.update( loads_after_label - stores )        # case 2

    # The C{pending} variable should have been reset at this point, because a
    # function should always end with a RETURN_VALUE opcode and therefore not
    # end in a LOAD_ATTR.
    assert pending is None

    # Recurse on inner function definitions, lambdas, generators, etc.
    for arg in co.co_consts:
        if isinstance(arg, types.CodeType):
            _find_loads_without_stores_in_code(arg, loads_without_stores)


def _find_earliest_backjump_label(bytecode):
    """
    Find the earliest target of a backward jump.

    These normally represent loops.

    For example, given the source code:
      >>> def f():
      ...     if foo1():
      ...         foo2()
      ...     else:
      ...         foo3()
      ...     foo4()
      ...     while foo5():  # L7
      ...         foo6()

    In python 2.6, the disassembled bytecode is::
      >> import dis
      >> dis.dis(f)
        2           0 LOAD_GLOBAL              0 (foo1)
                    3 CALL_FUNCTION            0
                    6 JUMP_IF_FALSE           11 (to 20)
                    9 POP_TOP
      <BLANKLINE>
        3          10 LOAD_GLOBAL              1 (foo2)
                   13 CALL_FUNCTION            0
                   16 POP_TOP
                   17 JUMP_FORWARD             8 (to 28)
              >>   20 POP_TOP
      <BLANKLINE>
        5          21 LOAD_GLOBAL              2 (foo3)
                   24 CALL_FUNCTION            0
                   27 POP_TOP
      <BLANKLINE>
        6     >>   28 LOAD_GLOBAL              3 (foo4)
                   31 CALL_FUNCTION            0
                   34 POP_TOP
      <BLANKLINE>
        7          35 SETUP_LOOP              22 (to 60)
              >>   38 LOAD_GLOBAL              4 (foo5)
                   41 CALL_FUNCTION            0
                   44 JUMP_IF_FALSE           11 (to 58)
                   47 POP_TOP
      <BLANKLINE>
        8          48 LOAD_GLOBAL              5 (foo6)
                   51 CALL_FUNCTION            0
                   54 POP_TOP
                   55 JUMP_ABSOLUTE           38
              >>   58 POP_TOP
                   59 POP_BLOCK
              >>   60 LOAD_CONST               0 (None)
                   63 RETURN_VALUE

    The earliest target of a backward jump would be the 'while' loop at L7, at
    bytecode offset 38::
      >> _find_earliest_backjump_label(f.func_code.co_code)
      38

    Note that in this example there are earlier targets of jumps at bytecode
    offsets 20 and 28, but those are targets of _forward_ jumps, and the
    clients of this function care about the earliest _backward_ jump.

    If there are no backward jumps, return an offset that points after the end
    of the bytecode.

    @type bytecode:
      C{bytes}
    @param bytecode:
      Compiled bytecode, e.g. C{function.func_code.co_code}.
    @rtype:
      C{int}
    @return:
      The earliest target of a backward jump, as an offset into the bytecode.
    """
    # Code based on dis.findlabels().
    from opcode import HAVE_ARGUMENT, hasjrel, hasjabs
    if not isinstance(bytecode, bytes):
        raise TypeError
    n = len(bytecode)
    earliest_backjump_label = n
    i = 0
    while i < n:
        c = bytecode[i]
        op = ord(c)
        i += 1
        if op < HAVE_ARGUMENT:
            continue
        oparg = ord(bytecode[i]) + ord(bytecode[i+1])*256
        i += 2
        label = None
        if op in hasjrel:
            label = i+oparg
        elif op in hasjabs:
            label = oparg
        else:
            # No label
            continue
        if label >= i:
            # Label is a forward jump
            continue
        # Found a backjump label.  Keep track of the earliest one.
        earliest_backjump_label = min(earliest_backjump_label, label)
    return earliest_backjump_label


def find_missing_imports(arg, namespaces):
    """
    Find symbols in the given code that require import.

    We consider a symbol to require import if we see an access ("Load" in AST
    terminology) without an import or assignment ("Store" in AST terminology)
    in the same lexical scope.

    For example, if we use an empty list of namespaces, then "os.path.join" is
    a symbol that requires import:
      >>> find_missing_imports("os.path.join", namespaces=[{}])
      ['os.path.join']

    But if the global namespace already has the "os" module imported, then we
    know that C{os} has a "path" attribute, which has a "join" attribute, so
    nothing needs import:
      >>> import os
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
      >>> find_missing_imports("import numpy; numpy.arange(x) + arange(x)", [{}])
      ['arange', 'x']

      >>> find_missing_imports("from numpy import pi; numpy.pi + pi + x", [{}])
      ['numpy.pi', 'x']

      >>> find_missing_imports("for x in range(3): print numpy.arange(x)", [{}])
      ['numpy.arange']

      >>> find_missing_imports("foo1 = func(); foo1.bar + foo2.bar", [{}])
      ['foo2.bar', 'func']

      >>> find_missing_imports("a.b.y = 1; a.b.x, a.b.y, a.b.z", [{}])
      ['a.b.x', 'a.b.z']

    find_missing_imports() parses the AST, so it understands scoping.  In the
    following example, C{x} is never undefined:
      >>> find_missing_imports("(lambda x: x*x)(7)", [{}])
      []

    but this example, C{x} is undefined at global scope:
      >>> find_missing_imports("(lambda x: x*x)(7) + x", [{}])
      ['x']

    The (unintuitive) rules for generator expressions and list comprehensions
    are handled correctly:
      >>> find_missing_imports("[x+y+z for x,y in [(1,2)]], y", [{}])
      ['z']

      >>> find_missing_imports("(x+y+z for x,y in [(1,2)]), y", [{}])
      ['y', 'z']

    Only fully-qualified names starting at top-level are included:

      >>> find_missing_imports("( ( a . b ) . x ) . y + ( c + d ) . x . y", [{}])
      ['a.b.x.y', 'c', 'd']

    @type arg:
      C{str}, C{ast.AST}, L{PythonBlock}, C{callable}, or C{types.CodeType}
    @param arg:
      Python code, either as source text, a parsed AST, or compiled code; can
      be as simple as a single qualified name, or as complex as an entire
      module text.
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Stack of namespaces of symbols that exist per scope.
    @rtype:
      C{list} of C{str}
    """
    namespaces = ScopeStack(namespaces)
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
            # Parse the string into an AST.
            node = ast.parse(arg) # may raise SyntaxError
            # Get missing imports from AST.
            return _find_missing_imports_in_ast(node, namespaces)
    elif isinstance(arg, PythonBlock):
        return _find_missing_imports_in_ast(arg.ast_node, namespaces)
    elif isinstance(arg, ast.AST):
        return _find_missing_imports_in_ast(arg, namespaces)
    elif isinstance(arg, types.CodeType):
        return _find_missing_imports_in_code(arg, namespaces)
    elif callable(arg):
        # Find the code object.
        try:
            co = arg.func_code
        except AttributeError:
            # User-defined callable
            try:
                co = arg.__call__.func_code
            except AttributeError:
                # Built-in function; no auto importing needed.
                return []
        # Get missing imports from code object.
        return _find_missing_imports_in_code(co, namespaces)
    else:
        raise TypeError(
            "find_missing_imports(): expected a string, AST node, or code object; got a %s"
            % (type(arg).__name__,))


def get_known_import(fullname, db=None):
    """
    Get the deepest known import.

    For example, suppose:
      - The user accessed "foo.bar.baz",
      - We know imports for "foo", "foo.bar", and "foo.bar.quux".

    Then we return "import foo.bar".

    @type fullname:
      L{DottedIdentifier}
    @param fullname:
      Fully-qualified name, such as "scipy.interpolate"
    """
    # Get the import database.
    db = ImportDB.interpret_arg(db, target_filename=".")
    fullname = DottedIdentifier(fullname)
    # Look for the "deepest" import we know about.  Suppose the user
    # accessed "foo.bar.baz".  If we have an auto-import for "foo.bar",
    # then import that.  (Presumably, the auto-import for "foo", if it
    # exists, refers to the same foo.)
    for partial_name in fullname.prefixes[::-1]:
        try:
            result = db.by_fullname_or_import_as[str(partial_name)]
            logger.debug("get_known_import(%r): found %r", fullname, result)
            return result
        except KeyError:
            logger.debug("get_known_import(%r): no known import for %r", fullname, partial_name)
            pass
    logger.debug("get_known_import(%r): found nothing", fullname)
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
      C{Import} or C{str}
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
    imp = Import(imp)
    if imp in _IMPORT_FAILED:
        logger.debug("Not attempting previously failed %r", imp)
        return False
    impas = imp.import_as
    name0 = impas.split(".", 1)[0]
    stmt = str(imp)
    logger.info(stmt)
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
        logger.info("Error attempting to %r: %s: %s", stmt, type(e).__name__, e)
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
            logger.info("  => Failed: pre-existing %r (%r) differs from imported %r",
                        name0, preexisting, name0)
            return False
    return True


def auto_import_symbol(fullname, namespaces, db=None, autoimported=None):
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
    @type db:
      L{ImportDB}
    @param db:
      Import database to use.
    @rtype:
      C{bool}
    @return:
      C{True} if the symbol was already in the namespace, or the auto-import
      succeeded; C{False} if the auto-import failed.
    """
    namespaces = ScopeStack(namespaces)
    if not symbol_needs_import(fullname, namespaces):
        return True
    if autoimported is None:
        autoimported = {}
    if DottedIdentifier(fullname) in autoimported:
        logger.debug("auto_import_symbol(%r): already attempted", fullname)
        return False
    # See whether there's a known import for this name.  This is mainly
    # important for things like "from numpy import arange".  Imports such as
    # "import sqlalchemy.orm" will also be handled by this, although it's less
    # important, since we're going to attempt that import anyway if it looks
    # like a "sqlalchemy" package is importable.
    imports = get_known_import(fullname, db=db)
    if imports is None:
        # No known imports.
        pass
    else:
        assert len(imports) >= 1
        if len(imports) > 1:
            # Doh, multiple imports.
            logger.info("Multiple candidate imports for %s.  Please pick one:", fullname)
            for imp in imports:
                logger.info("  %s", imp)
            autoimported[DottedIdentifier(fullname)] = False
            return False
        imp, = imports
        if symbol_needs_import(imp.import_as, namespaces=namespaces):
            # We're ready for some real action.  The input code references a
            # name/attribute that (a) is not locally assigned, (b) is not a
            # global, (c) is not yet imported, (d) is a known auto-import, (e)
            # has only one definition
            # TODO: label which known_imports file the autoimport came from
            if not _try_import(imp, namespaces[-1]):
                # Failed; don't do anything else.
                autoimported[DottedIdentifier(fullname)] = False
                return False
            # Succeeded.
            autoimported[DottedIdentifier(imp.import_as)] = True
            if imp.import_as == fullname:
                # We got what we wanted, so nothing more to do.
                return True
            if imp.import_as != imp.fullname:
                # This is not just an 'import foo.bar'; rather, it's a 'import
                # foo.bar as baz' or 'from foo import bar'.  So don't go any
                # further.
                return True
        # Fall through.
    # We haven't yet imported what we want.  Either there was no entry in the
    # known imports database, or it wasn't "complete" (e.g. the user wanted
    # "foo.bar.baz", and the known imports database only knew about "import
    # foo.bar").  For each component that may need importing, check if the
    # loader thinks it should be importable, and if so import it.
    for pmodule in ModuleHandle(fullname).ancestors:
        if not symbol_needs_import(pmodule.name, namespaces):
            continue
        pmodule_name = DottedIdentifier(pmodule.name)
        if pmodule_name in autoimported:
            if not autoimported[pmodule_name]:
                logger.debug("auto_import_symbol(%r): stopping because "
                             "already previously failed to autoimport %s",
                             fullname, pmodule_name)
                return False
        if not pmodule.module_if_importable:
            logger.debug("auto_import_symbol(%r): %r is not importable",
                         fullname, pmodule)
            autoimported[pmodule_name] = False
            return False
        result = _try_import("import %s" % pmodule_name, namespaces[-1])
        assert result
        autoimported[pmodule_name] = True
    return True


def auto_import(arg, namespaces, db=None, autoimported=None):
    """
    Parse C{arg} for symbols that need to be imported and automatically import
    them.

    @type arg:
      C{str}, C{ast.AST}, L{PythonBlock}, C{callable}, or C{types.CodeType}
    @param arg:
      Python code, either as source text, a parsed AST, or compiled code; can
      be as simple as a single qualified name, or as complex as an entire
      module text.
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Namespaces to check.  Namespace[-1] is the namespace to import into.
    @type db:
      L{ImportDB}
    @param db:
      Import database to use.
    @type autoimported:
      C{dict}
    @param autoimported:
      If not C{None}, then a dictionary of identifiers already attempted.
      C{auto_import} will not attempt to auto-import symbols already in this
      dictionary, and will add attempted symbols to this dictionary, with
      value C{True} if the autoimport succeeded, or C{False} if the autoimport
      did not succeed.
    @rtype:
      C{bool}
    @return:
      C{True} if all symbols are already in the namespace or successfully
      auto-imported; C{False} if any auto-imports failed.
    """
    namespaces = ScopeStack(namespaces)
    if isinstance(arg, PythonBlock):
        filename = arg.filename
    else:
        filename = "."
    try:
        fullnames = find_missing_imports(arg, namespaces)
    except SyntaxError:
        logger.debug("syntax error parsing %r", arg)
        return False
    logger.debug("Missing imports: %r", fullnames)
    if not fullnames:
        return True
    if autoimported is None:
        autoimported = {}
    db = ImportDB.interpret_arg(db, target_filename=filename)
    ok = True
    for fullname in fullnames:
        ok &= auto_import_symbol(fullname, namespaces, db, autoimported)
    return ok


def auto_eval(arg, filename=None, mode=None,
              flags=None, auto_flags=True, globals=None, locals=None,
              db=None):
    """
    Evaluate/execute the given code, automatically importing as needed.

    C{auto_eval} will default the compilation C{mode} to "eval" if possible:
      >>> auto_eval("b64decode('aGVsbG8=')") + "!"
      [PYFLYBY] from base64 import b64decode
      'hello!'

    C{auto_eval} will default the compilation C{mode} to "exec" if the input
    is not a single expression:
      >>> auto_eval("if True: print b64decode('aGVsbG8=')")
      [PYFLYBY] from base64 import b64decode
      hello

    This is roughly equivalent to "auto_import(arg); eval(arg)", but handles
    details better and more efficiently.

    @type arg:
      C{str}, C{ast.AST}, C{code}, L{Filename}, L{FileText}, L{PythonBlock}
    @param arg:
      Code to evaluate.
    @type filename:
      C{str}
    @param filename:
      Filename for compilation error messages.  If C{None}, defaults to
      C{arg.filename} if relevant, else C{"<stdin>"}.
    @type mode:
      C{str}
    @param mode:
      Compilation mode: "automatic", "exec", "single", or "eval".  "exec",
      "single", and "eval" work as the built-in C{compile} function do.
      If C{None}, then default to "eval" if the input is a string with a
      single expression, else "exec".
    @type flags:
      C{CompilerFlags} or convertible (C{int}, C{list} of C{str}, etc.)
    @param flags:
      Compilation feature flags, e.g. ["division", "with_statement"].  If
      C{None}, defaults to no flags.  Does not inherit flags from parent
      scope.
    @type auto_flags:
      C{bool}
    @param auto_flags:
      Whether to try other flags if C{flags} causes SyntaxError.
    @type globals:
      C{dict}
    @param globals:
      Globals for evaluation.  If C{None}, use an empty dictionary.
    @type locals:
      C{dict}
    @param locals:
      Locals for evaluation.  If C{None}, use C{globals}.
    @type db:
      L{ImportDB}
    @param db:
      Import database to use.
    @return:
      Result of evaluation (for mode="eval")
    """
    flags = CompilerFlags(flags)
    if isinstance(arg, (basestring, Filename, FileText, PythonBlock)):
        block = PythonBlock(arg, filename=filename, flags=flags,
                            auto_flags=auto_flags)
        flags = block.flags
        filename = block.filename
        arg = block.parse(mode=mode)
    elif isinstance(arg, (ast.AST, types.CodeType)):
        pass
    else:
        raise TypeError(
            "auto_eval(): expected some form of code; got a %s"
            % (type(arg).__name__,))
    # Canonicalize other args.
    if filename:
        filename = Filename(filename)
    else:
        filename = None
    if globals is None:
        globals = {}
    if locals is None:
        locals = globals
    db = ImportDB.interpret_arg(db, target_filename=filename)
    namespaces = [globals, locals]
    # Import as needed.
    auto_import(arg, namespaces, db)
    # Compile from AST to code object.
    if isinstance(arg, types.CodeType):
        code = arg
    else:
        # Infer mode from ast object.
        mode = infer_compile_mode(arg)
        # Compile ast node => code object.  This step is necessary because
        # eval() doesn't work on AST objects.  We don't need to pass C{flags}
        # to compile() because flags are irrelevant when we already have an
        # AST node.
        code = compile(arg, str(filename or "<unknown>"), mode)
    # Evaluate/execute.
    return eval(code, globals, locals)


def load_symbol(fullname, namespaces, autoimport=False, db=None,
                autoimported=None):
    """
    Load the symbol C{fullname}.

      >>> import os
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
    @type db:
      L{ImportDB}
    @param db:
      Import database to use when C{autoimport=True}.
    @return:
      Object.
    @raise AttributeError:
      Object was not found.
    """
    namespaces = ScopeStack(namespaces)
    if autoimport:
        # Auto-import the symbol first.
        # We do the lookup as a separate step after auto-import.  (An
        # alternative design could be to have auto_import_symbol() return the
        # symbol if possible.  We don't do that because most users of
        # auto_import_symbol() don't need to follow down arbitrary (possibly
        # non-module) attributes.)
        auto_import_symbol(fullname, namespaces, db, autoimported=autoimported)
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
