
from __future__ import absolute_import, division, with_statement

import ast
from   collections              import defaultdict, namedtuple

from   pyflyby.file             import Filename
from   pyflyby.flags            import CompilerFlags
from   pyflyby.format           import FormatParams, pyfill
from   pyflyby.parse            import PythonBlock, PythonStatement
from   pyflyby.util             import (Inf, cached_attribute, dotted_prefixes,
                                        longest_common_prefix, stable_unique)

class ImportFormatParams(FormatParams):
    align_imports = True
    """
    Whether and how to align 'from modulename import aliases...'.  If C{True},
    then the 'import' keywords will be aligned within a block.  If an integer,
    then the 'import' keyword will always be at that column.  They will be
    wrapped if necessary.
    """

    from_spaces = 1
    """
    The number of spaces after the 'from' keyword.  (Must be at least 1.)
    """

    separate_from_imports = True
    """
    Whether all 'from ... import ...' in an import block should come after
    'import ...' statements.  C{separate_from_imports = False} works well with
    C{from_spaces = 3}.  ('from __future__ import ...' always comes first.)
    """

    align_future = False
    """
    Whether 'from __future__ import ...' statements should be aligned with
    others.  If False, uses a single space after the 'from' and 'import'
    keywords.
    """


class NonImportStatementError(TypeError):
    """
    Unexpectedly got a statement that wasn't an import.
    """

class ConflictingImportsError(ValueError):
    pass

ImportSplit = namedtuple("ImportSplit",
                         "module_name member_name import_as")
"""
Representation of a single import at the token level::
  from [...]<module_name> import <member_name> as <import_as>

If <module_name> is C{None}, then there is no "from" clause; instead just::
  import <member_name> as <import_as>
"""

class Import(object):
    """
    Representation of the desire to import a single name into the current
    namespace.

      >>> Import.from_parts(".foo.bar", "bar")
      Import('from .foo import bar')

      >>> Import("from . import foo")
      Import('from . import foo')

      >>> Import("from . import foo").fullname
      '.foo'

      >>> Import("import   foo . bar")
      Import('import foo.bar')

      >>> Import("import   foo . bar  as  baz")
      Import('from foo import bar as baz')

    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, ImportSplit):
            return cls.from_split(arg)
        if isinstance(arg, (ImportStatement, PythonStatement, str)):
            return cls.from_statement(arg)
        raise TypeError

    @classmethod
    def from_parts(cls, fullname, import_as):
        if not isinstance(fullname, str):
            raise TypeError
        if not isinstance(import_as, str):
            raise TypeError
        self = object.__new__(cls)
        self.fullname = fullname
        self.import_as = import_as
        return self

    @classmethod
    def from_statement(cls, statement):
        """
        @type statement:
          L{ImportStatement} or convertible (L{PythonStatement}, C{str})
        @rtype:
          L{Import}
        """
        statement = ImportStatement(statement)
        imports = statement.imports
        if len(imports) != 1:
            raise ValueError(
                "Got %d imports instead of 1 in %r" % (len(imports), statement))
        return imports[0]

    @cached_attribute
    def split(self):
        """
        Split this L{Import} into C{module_name}, C{member_name},
        C{import_as}.

          >>> Import.from_parts(".foo.bar", "bar").split
          ImportSplit(module_name='.foo', member_name='bar', import_as=None)

          >>> Import("from . import foo").split
          ImportSplit(module_name='.', member_name='foo', import_as=None)

          >>> Import.from_parts(".foo", "foo").split
          ImportSplit(module_name='.', member_name='foo', import_as=None)

          >>> Import.from_parts("foo.bar", "foo.bar").split
          ImportSplit(module_name=None, member_name='foo.bar', import_as=None)

        @rtype:
          L{ImportSplit}
        """
        if self.import_as == self.fullname:
            return ImportSplit(None, self.fullname, None)
        level = 0
        qname = self.fullname
        for level, char in enumerate(qname):
            if char != '.':
                break
        prefix = qname[:level]
        qname = qname[level:]
        if '.' in qname:
            module_name, member_name = qname.rsplit(".", 1)
        else:
            module_name = ''
            member_name = qname
        module_name = prefix + module_name
        import_as = self.import_as
        if import_as == member_name:
            import_as = None
        return ImportSplit(module_name or None, member_name, import_as)

    @classmethod
    def from_split(cls, impsplit):
        """
        Construct an L{Import} instance from C{module_name}, C{member_name},
        C{import_as}.

        @rtype:
          L{Import}
        """
        impsplit = ImportSplit(*impsplit)
        module_name, member_name, import_as = impsplit
        if import_as is None:
            import_as = member_name
        if module_name is None:
            result = cls.from_parts(member_name, import_as)
        else:
            fullname = "%s%s%s" % (
                module_name,
                "" if module_name.endswith(".") else ".",
                member_name)
            result = cls.from_parts(fullname, import_as)
        # result.split will usually be the same as impsplit, but could be
        # different if the input was 'import foo.bar as baz', which we
        # canonicalize to 'from foo import bar as baz'.
        return result

    def prefix_match(self, imp):
        """
        Return the longest common prefix between C{self} and C{imp}.

          >>> Import("import ab.cd.ef").prefix_match(Import("import ab.cd.xy"))
          ('ab', 'cd')

        @type imp:
          L{Import}
        @rtype:
          C{tuple} of C{str}
        """
        imp = Import(imp)
        n1 = self.fullname.split('.')
        n2 = imp.fullname.split('.')
        return tuple(longest_common_prefix(n1, n2))

    def replace(self, prefix, replacement):
        """
        Return a new C{Import} that replaces C{prefix} with C{replacement}.

          >>> Import("from aa.bb import cc").replace("aa.bb", "xx.yy")
          Import('from xx.yy import cc')

          >>> Import("from aa import bb").replace("aa.bb", "xx.yy")
          Import('from xx import yy as bb')

        @rtype:
          C{Import}
        """
        prefix_parts = prefix.split('.')
        replacement_parts = replacement.split('.')
        fullname_parts = self.fullname.split('.')
        if fullname_parts[:len(prefix_parts)] != prefix_parts:
            # No prefix match.
            return self
        fullname_parts[:len(prefix_parts)] = replacement_parts
        import_as_parts = self.import_as.split('.')
        if import_as_parts[:len(prefix_parts)] == prefix_parts:
            import_as_parts[:len(prefix_parts)] = replacement_parts
        return self.from_parts('.'.join(fullname_parts),
                               '.'.join(import_as_parts))

    @cached_attribute
    def flags(self):
        """
        If this is a __future__ import, then the compiler_flag associated with
        it.  Otherwise, 0.
        """
        if self.split.module_name == "__future__":
            return CompilerFlags(self.split.member_name)
        else:
            return CompilerFlags(0)

    @property
    def _data(self):
        return (self.fullname, self.import_as)

    def pretty_print(self, params=FormatParams()):
        return ImportStatement([self]).pretty_print(params)

    def __str__(self):
        return self.pretty_print(FormatParams(max_line_length=Inf)).rstrip()

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, str(self))

    def __hash__(self):
        return hash(self._data)

    def __cmp__(self, other):
        return cmp(self._data, other._data)


class ImportStatement(object):
    """
    Token-level representation of an import statement containing multiple
    imports from a single module.  Corresponds to an C{ast.ImportFrom} or
    C{ast.Import}.
    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonStatement, str)):
            return cls.from_statement(arg)
        if isinstance(arg, (ast.ImportFrom, ast.Import)):
            return cls.from_ast_node(arg)
        if isinstance(arg, Import):
            return cls.from_imports([arg])
        if isinstance(arg, (tuple, list)) and len(arg):
            if isinstance(arg[0], Import):
                return cls.from_imports(arg)
        raise TypeError

    @classmethod
    def from_parts(cls, fromname, aliases):
        self = object.__new__(cls)
        self.fromname = fromname
        if not len(aliases):
            raise ValueError
        def interpret_alias(arg):
            if isinstance(arg, str):
                return (arg, None)
            if not isinstance(arg, tuple):
                raise TypeError
            if not len(arg) == 2:
                raise TypeError
            if not isinstance(arg[0], str):
                raise TypeError
            if not (arg[1] is None or isinstance(arg[1], str)):
                raise TypeError
            return arg
        self.aliases = tuple(interpret_alias(a) for a in aliases)
        return self

    @classmethod
    def from_statement(cls, statement):
        """
          >>> ImportStatement.from_statement("from foo  import bar, bar2, bar")
          ImportStatement('from foo import bar, bar2, bar')

          >>> ImportStatement.from_statement("from foo  import bar as bar")
          ImportStatement('from foo import bar as bar')

          >>> ImportStatement.from_statement("from foo.bar  import baz")
          ImportStatement('from foo.bar import baz')

          >>> ImportStatement.from_statement("import  foo.bar")
          ImportStatement('import foo.bar')

          >>> ImportStatement.from_statement("from .foo  import bar")
          ImportStatement('from .foo import bar')

          >>> ImportStatement.from_statement("from .  import bar, bar2")
          ImportStatement('from . import bar, bar2')

        @type statement:
          L{PythonStatement}
        @rtype:
          L{ImportStatement}
        """
        statement = PythonStatement(statement)
        return cls.from_ast_node(statement.ast_node)

    @classmethod
    def from_ast_node(cls, node):
        """
        Construct an L{ImportStatement} from an L{ast} node.

        @rtype:
          L{ImportStatement}
        """
        if isinstance(node, ast.ImportFrom):
            assert isinstance(node.module, str)
            fromname = '.' * node.level + node.module
        elif isinstance(node, ast.Import):
            fromname = None
        else:
            raise NonImportStatementError
        aliases = [ (alias.name, alias.asname) for alias in node.names ]
        return cls.from_parts(fromname, aliases)

    @classmethod
    def from_imports(cls, imports):
        """
        Construct an L{ImportStatement} from a sequence of C{Import}s.  They
        must all have the same C{fromname}.

        @type imports:
          Sequence of L{Import}s
        @rtype:
          L{ImportStatement}
        """
        if not all(isinstance(imp, Import) for imp in imports):
            raise TypeError
        if not len(imports) > 0:
            raise ValueError
        module_names = set(imp.split.module_name for imp in imports)
        if len(module_names) > 1:
            raise Exception(
                "Inconsistent module names %r" % (sorted(module_names),))
        fromname = list(module_names)[0]
        aliases = [ imp.split[1:] for imp in imports ]
        return cls.from_parts(fromname, aliases)

    @cached_attribute
    def imports(self):
        """
        Return a sequence of L{Import}s.

        @rtype:
          C{tuple} of L{Import}s
        """
        return tuple(
            Import.from_split((self.fromname, alias[0], alias[1]))
            for alias in self.aliases)

    @cached_attribute
    def flags(self):
        """
        If this is a __future__ import, then the bitwise-ORed of the
        compiler_flag values associated with the features.  Otherwise, 0.
        """
        return CompilerFlags(*[imp.flags for imp in self.imports])

    def pretty_print(self, params=FormatParams(),
                     import_column=None, from_spaces=1):
        """
        Pretty-print into a single string.

        @type params:
          L{FormatParams}
        @param modulename_ljust:
          Number of characters to left-justify the 'from' name.
        @rtype:
          C{str}
        """
        s0 = ''
        s = ''
        assert from_spaces >= 1
        if self.fromname is not None:
            s += "from%s%s " % (' ' * from_spaces, self.fromname)
            if import_column is not None:
                if len(s) > import_column:
                    # The caller wants the 'import' statement lined up left of
                    # where the current end of the line is.  So wrap it
                    # specially like this::
                    #     from foo     import ...
                    #     from foo.bar.baz \
                    #                  import ...
                    s0 = s + '\\\n'
                    s = ' ' * import_column
                else:
                    s = s.ljust(import_column)
        s += "import "
        tokens = []
        for importname, asname in self.aliases:
            if asname is not None:
                t = "%s as %s" % (importname, asname)
            else:
                t = "%s" % (importname,)
            tokens.append(t)
        return s0 + pyfill(s, tokens, params=params)

    @property
    def _data(self):
        return (self.fromname, self.aliases)

    def __repr__(self):
        # We could also return "%s.from_parts%r" % (type(self).__name__,
        # self._data); but returning pretty-printed version is friendlier.
        return "%s(%r)" % (type(self).__name__, self.pretty_print(
                FormatParams(max_line_length=Inf)).rstrip())

    def __hash__(self):
        return hash(self._data)

    def __cmp__(self, other):
        return cmp(self._data, other._data)


class NoSuchImportError(ValueError):
    pass

class Imports(object):
    """
    Representation of a set of imports organized into import statements.
    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonBlock, Filename, str)):
            return cls.from_code(arg)
        if isinstance(arg, (tuple, list)) and len(arg):
            if isinstance(arg[0], Import):
                return cls.from_imports(arg)
            if isinstance(arg[0], ImportStatement):
                return cls.from_statements(arg)
            if isinstance(arg[0], PythonStatement):
                return cls.from_pystatements(arg)
            if isinstance(arg[0], (PythonBlock, Filename, str)):
                return cls.from_code(arg)
        raise TypeError

    @classmethod
    def from_imports(cls, imports, exclude_imports=()):
        """
        @type imports:
          Sequence of L{Imports}
        @type exclude_imports
          Sequence of L{Imports}
        @rtype:
          L{Imports}
        """
        self = object.__new__(cls)
        # Keep track of excluded imports.  The reason we explicitly keep track
        # of exclusions is for the sake of by_fullname_or_import_as.  For
        # example, consider the following import statements:
        #   from foo1 import bar1
        #   from foo2 import bar2
        # __remove__:
        #   import foo2
        # We want by_fullname_or_import_as to include "import foo1" but not
        # "foo2".
        self.exclude_imports = frozenset(Import(imp) for imp in exclude_imports)
        self.orig_imports = tuple(Import(imp) for imp in imports
                                  if imp not in self.exclude_imports)
        return self

    @classmethod
    def from_statements(cls, statements):
        """
        @type statements:
          Sequence of L{ImportStatement}s
        @rtype:
          L{Imports}
        """
        # Flatten into a sequence of C{Import}s.  We'll rebuild as
        # C{ImportStatement}s later after merging canonically.
        imports = [
            imp
            for stmt in statements
            for imp in stmt.imports]
        return cls.from_imports(imports)

    @classmethod
    def from_pystatements(cls, statements, filter_nonimports=False):
        """
        @type statements:
          Sequence of L{PythonStatement}s
        @rtype:
          L{Imports}
        """
        statements = [PythonStatement(stmt) for stmt in statements]
        # Ignore comments/blanks.
        statements = [statement for statement in statements
                      if not statement.is_comment_or_blank]
        # Check for non-imports.
        if filter_nonimports:
            statements = [statement for statement in statements
                          if statement.is_import]
        else:
            for statement in statements:
                if not statement.is_import:
                    raise NonImportStatementError(
                        "Got non-import statement %r" % (statement,))
        # Convert to sequence of C{ImportStatement}s.
        import_statements = [ImportStatement(statement)
                             for statement in statements]
        return cls.from_statements(import_statements)

    @classmethod
    def from_code(cls, codeblocks, filter_nonimports=False):
        """
        @type codeblocks:
          sequence of L{PythonBlock}s (or convertibles such as C{Filename},
          C{str})
        @rtype:
          L{Imports}
        """
        if not isinstance(codeblocks, (tuple, list)):
            codeblocks = (codeblocks,)
        codeblocks = [PythonBlock(b) for b in codeblocks]
        statements = [s for b in codeblocks for s in b.statements]
        return cls.from_pystatements(statements, filter_nonimports)

    def with_imports(self, new_imports):
        """
        Return a copy of self with new imports added.

          >>> imp = Import('import m.t2a as t2b')
          >>> Imports('from m import t1, t2, t3').with_imports([imp])
          Imports([ImportStatement('from m import t1, t2, t2a as t2b, t3')])

        @type new_imports:
          Sequence of L{Import} (or convertibles)
        @rtype:
          L{Imports}
        """
        if isinstance(new_imports, Imports):
            new_imports = new_imports.imports
        new_imports = tuple(Import(imp) for imp in new_imports)
        return type(self).from_imports(self.orig_imports + new_imports,
                                       exclude_imports=self.exclude_imports)

    def without_imports(self, import_exclusions, strict=True):
        """
        Return a copy of self without the given imports indexed by
        C{import_as}.

          >>> imports = Imports('from m import t1, t2, t3, t4')
          >>> imports.without_imports(['from m import t3'])
          Imports([ImportStatement('from m import t1, t2, t4')])

        @type import_exclusions:
          Sequence of L{Import}
        @param strict:
          If C{True}, raise L{NoSuchImportError} if any import in
          C{import_exclusions} is not in C{self}.  If C{False}, ignore imports
          in C{import_exclusions} not in C{self}.
        @rtype:
          L{Imports}
        """
        if isinstance(import_exclusions, Imports):
            import_exclusions = import_exclusions.imports
        import_exclusions = set(Import(imp) for imp in import_exclusions)
        imports_removed = set()
        new_imports = []
        for imp in self.orig_imports:
            if imp in import_exclusions:
                imports_removed.add(imp)
                continue
            new_imports.append(imp)
        if strict:
            imports_not_removed = import_exclusions - imports_removed
            if imports_not_removed:
                raise NoSuchImportError(
                    "Import database does not contain import(s) %r"
                    % (sorted(imports_not_removed),))
        return type(self).from_imports(
            new_imports,
            exclude_imports=(self.exclude_imports | import_exclusions))

    @cached_attribute
    def _by_module_name(self):
        """
        @return:
          (mapping from name to __future__ imports,
           mapping from name to non-'from' imports,
           mapping from name to 'from' imports)
        """
        ftr_imports = defaultdict(set)
        pkg_imports = defaultdict(set)
        frm_imports = defaultdict(set)
        for imp in self.orig_imports:
            module_name, member_name, import_as = imp.split
            if module_name is None:
                pkg_imports[member_name].add(imp)
            elif module_name == '__future__':
                ftr_imports[module_name].add(imp)
            else:
                frm_imports[module_name].add(imp)
        return tuple(
            dict( (k, frozenset(v))
                  for k, v in imports.iteritems())
            for imports in [ftr_imports, pkg_imports, frm_imports])

    def get_statements(self, separate_from_imports=True):
        """
        Canonicalized L{ImportStatement}s.
        These have been merged by module and sorted.

        @rtype:
          C{tuple} of L{ImportStatement}s
        """
        groups = self._by_module_name
        if not separate_from_imports:
            def union_dicts(*dicts):
                result = {}
                for label, dict in enumerate(dicts):
                    for k, v in dict.iteritems():
                        result[(k, label)] = v
                return result
            groups = [groups[0], union_dicts(*groups[1:])]
        return tuple(
            ImportStatement(sorted(imports))
            for importgroup in groups
            for _, imports in sorted(importgroup.items()))

    @cached_attribute
    def statements(self):
        """
        Canonicalized L{ImportStatement}s.
        These have been merged by module and sorted.

        @rtype:
          C{tuple} of L{ImportStatement}s
        """
        return self.get_statements(separate_from_imports=True)

    @cached_attribute
    def imports(self):
        """
        Canonicalized imports, in the same order as C{self.statements}.

        @rtype:
          C{tuple} of L{Import}s
        """
        return tuple(
            imp
            for importgroup in self._by_module_name
            for imports in importgroup.values()
            for imp in sorted(imports))

    @cached_attribute
    def by_import_as(self):
        """
        Map from C{import_as} to L{Import}.

          >>> Imports('from aa.bb import cc as dd').by_import_as
          {'dd': (Import('from aa.bb import cc as dd'),)}

        @rtype:
          C{dict} mapping from C{str} to tuple of L{Import}s
        """
        d = defaultdict(list)
        for imp in self.orig_imports:
            d[imp.import_as].append(imp)
        return dict( (k, tuple(stable_unique(v)))
                     for k, v in d.iteritems() )

    @cached_attribute
    def by_fullname_or_import_as(self):
        """
        Map from C{fullname} and C{import_as} to L{Import}s.

          >>> import pprint
          >>> db = Imports('from aa.bb import cc as dd')
          >>> pprint.pprint(db.by_fullname_or_import_as)
          {'aa': (Import('import aa'),),
           'aa.bb': (Import('import aa.bb'),),
           'dd': (Import('from aa.bb import cc as dd'),)}

        @rtype:
          C{dict} mapping from C{str} to tuple of L{Import}s
        """
        d = defaultdict(set)
        for imp in self.orig_imports:
            # Given an import like "from foo.bar import quux as QUUX", add the
            # following entries:
            #   - "QUUX"         => "from foo.bar import quux as QUUX"
            #   - "foo.bar"      => "import foo.bar"
            #   - "foo"          => "import foo"
            # We don't include an entry labeled "quux" because the user has
            # implied he doesn't want to pollute the global namespace with
            # "quux", only "QUUX".
            d[imp.import_as].add(imp)
            for prefix in dotted_prefixes(imp.fullname)[:-1]:
                d[prefix].add(Import.from_parts(prefix, prefix))
        return dict( (k, tuple(sorted(v - self.exclude_imports)))
                     for k, v in d.iteritems())

    @cached_attribute
    def member_names(self):
        """
        Map from parent module/package C{fullname} to known member names.

          >>> db = Imports("import numpy.linalg.info\\nfrom sys import exit as EXIT")
          >>> import pprint
          >>> pprint.pprint(db.member_names)
          {'': ('EXIT', 'numpy', 'sys'),
           'numpy': ('linalg',),
           'numpy.linalg': ('info',),
           'sys': ('exit',)}

        This is used by the autoimporter module for implementing tab completion.

        @rtype:
          C{dict} mapping from C{str} to tuple of C{str}
        """
        d = defaultdict(set)
        for imp in self.orig_imports:
            if '.' not in imp.import_as:
                d[""].add(imp.import_as)
            prefixes = dotted_prefixes(imp.fullname)
            d[""].add(prefixes[0])
            for prefix in prefixes[1:]:
                splt = prefix.rsplit(".", 1)
                d[splt[0]].add(splt[1])
        return dict( (k, tuple(sorted(v)))
                     for k, v in d.iteritems() )

    @cached_attribute
    def conflicting_imports(self):
        """
        Returns imports that conflict with each other.

          >>> Imports('import b\\nfrom f import a as b\\n').conflicting_imports
          ('b',)

          >>> Imports('import b\\nfrom f import a\\n').conflicting_imports
          ()

        @rtype:
          C{bool}
        """
        return tuple(
            k
            for k, v in self.by_import_as.iteritems()
            if len(v) > 1)

    @cached_attribute
    def flags(self):
        """
        If this contains __future__ imports, then the bitwise-ORed of the
        compiler_flag values associated with the features.  Otherwise, 0.
        """
        imports = self._by_module_name[0].get("__future__", [])
        return CompilerFlags(*[imp.flags for imp in imports])

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, list(self.statements))

    def pretty_print(self, params=ImportFormatParams(), allow_conflicts=False):
        """
        Pretty-print a block of import statements into a single string.

        @type params:
          L{ImportFormatParams}
        @rtype:
          C{str}
        """
        if not allow_conflicts and self.conflicting_imports:
            raise ConflictingImportsError(
                "Refusing to pretty-print because of conflicting imports: " +
                '; '.join(
                    "%r imported as %r" % (
                        [imp.fullname for imp in self.by_import_as[i]], i)
                    for i in self.conflicting_imports))
        from_spaces = max(1, params.from_spaces)
        def do_align(statement):
            return statement.fromname != '__future__' or params.align_future
        def pp(statement, import_column):
            if do_align(statement):
                return statement.pretty_print(
                    params=params, import_column=import_column,
                    from_spaces=from_spaces)
            else:
                return statement.pretty_print(
                    params=params, import_column=None, from_spaces=1)
        statements = self.get_statements(
            separate_from_imports=params.separate_from_imports)
        def isint(x): return isinstance(x, int) and not isinstance(x, bool)
        if not statements:
            import_column = None
        elif isinstance(params.align_imports, bool):
            if params.align_imports:
                fromimp_stmts = [
                    s for s in statements if s.fromname and do_align(s)]
                if fromimp_stmts:
                    import_column = (
                        max(len(s.fromname) for s in fromimp_stmts)
                        + from_spaces + 5)
                else:
                    import_column = None
            else:
                import_column = None
        elif isinstance(params.align_imports, int):
            import_column = params.align_imports
        elif isinstance(params.align_imports, (tuple, list, set)):
            # If given a set of candidate alignment columns, then try each
            # alignment column and pick the one that yields the fewest number
            # of output lines.
            if not all(isinstance(x, int) for x in params.align_imports):
                raise TypeError("expected set of integers; got %r"
                                % (params.align_imports,))
            candidates = sorted(set(params.align_imports))
            if len(candidates) == 0:
                raise ValueError("list of zero candidate alignment columns specified")
            elif len(candidates) == 1:
                # Optimization.
                import_column = next(iter(candidates))
            else:
                def argmin(map):
                    items = iter(sorted(map.items()))
                    min_k, min_v = next(items)
                    for k, v in items:
                        if v < min_v:
                            min_k = k
                            min_v = v
                    return min_k
                def count_lines(import_column):
                    return sum(
                        s.pretty_print(
                            params=params, import_column=import_column,
                            from_spaces=from_spaces).count("\n")
                        for s in statements)
                # Construct a map from alignment column to total number of
                # lines.
                col2length = dict((c, count_lines(c)) for c in candidates)
                # Pick the column that yields the fewest lines.  Break ties by
                # picking the smaller column.
                import_column = argmin(col2length)
        else:
            raise TypeError(
                "Imports.pretty_print(): unexpected params.align_imports type %s"
                % (type(params.align_imports).__name__,))
        return ''.join(pp(statement, import_column) for statement in statements)
