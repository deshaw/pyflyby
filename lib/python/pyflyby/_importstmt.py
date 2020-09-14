# pyflyby/_importstmt.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import ast
from   collections              import namedtuple
from   functools                import total_ordering

from   pyflyby._flags           import CompilerFlags
from   pyflyby._format          import FormatParams, pyfill
from   pyflyby._idents          import is_identifier
from   pyflyby._parse           import PythonStatement
from   pyflyby._util            import (Inf, cached_attribute, cmp,
                                        longest_common_prefix)


class ImportFormatParams(FormatParams):
    align_imports = True
    """
    Whether and how to align 'from modulename import aliases...'.  If ``True``,
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
    'import ...' statements.  ``separate_from_imports = False`` works well with
    ``from_spaces = 3``.  ('from __future__ import ...' always comes first.)
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

ImportSplit = namedtuple("ImportSplit",
                         "module_name member_name import_as")
"""
Representation of a single import at the token level::

  from [...]<module_name> import <member_name> as <import_as>

If <module_name> is ``None``, then there is no "from" clause; instead just::
  import <member_name> as <import_as>
"""

@total_ordering
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

      >>> Import("import   foo . bar  as  bar")
      Import('from foo import bar')

      >>> Import("foo.bar")
      Import('from foo import bar')

    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, ImportSplit):
            return cls.from_split(arg)
        if isinstance(arg, (ImportStatement, PythonStatement)):
            return cls._from_statement(arg)
        if isinstance(arg, str):
            return cls._from_identifier_or_statement(arg)
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
    def _from_statement(cls, statement):
        """
        :type statement:
          `ImportStatement` or convertible (`PythonStatement`, ``str``)
        :rtype:
          `Import`
        """
        statement = ImportStatement(statement)
        imports = statement.imports
        if len(imports) != 1:
            raise ValueError(
                "Got %d imports instead of 1 in %r" % (len(imports), statement))
        return imports[0]

    @classmethod
    def _from_identifier_or_statement(cls, arg):
        """
        Parse either a raw identifier or a statement.

          >>> Import._from_identifier_or_statement('foo.bar.baz')
          Import('from foo.bar import baz')

          >>> Import._from_identifier_or_statement('import foo.bar.baz')
          Import('import foo.bar.baz')

        :rtype:
          `Import`
        """
        if is_identifier(arg, dotted=True):
            return cls.from_parts(arg, arg.split('.')[-1])
        else:
            return cls._from_statement(arg)

    @cached_attribute
    def split(self):
        """
        Split this `Import` into a ``ImportSplit`` which represents the
        token-level ``module_name``, ``member_name``, ``import_as``.

        Note that at the token level, ``import_as`` can be ``None`` to represent
        that the import statement doesn't have an "as ..." clause, whereas the
        ``import_as`` attribute on an ``Import`` object is never ``None``.

          >>> Import.from_parts(".foo.bar", "bar").split
          ImportSplit(module_name='.foo', member_name='bar', import_as=None)

          >>> Import("from . import foo").split
          ImportSplit(module_name='.', member_name='foo', import_as=None)

          >>> Import.from_parts(".foo", "foo").split
          ImportSplit(module_name='.', member_name='foo', import_as=None)

          >>> Import.from_parts("foo.bar", "foo.bar").split
          ImportSplit(module_name=None, member_name='foo.bar', import_as=None)

        :rtype:
          `ImportSplit`
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
        Construct an `Import` instance from ``module_name``, ``member_name``,
        ``import_as``.

        :rtype:
          `Import`
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
        Return the longest common prefix between ``self`` and ``imp``.

          >>> Import("import ab.cd.ef").prefix_match(Import("import ab.cd.xy"))
          ('ab', 'cd')

        :type imp:
          `Import`
        :rtype:
          ``tuple`` of ``str``
        """
        imp = Import(imp)
        n1 = self.fullname.split('.')
        n2 = imp.fullname.split('.')
        return tuple(longest_common_prefix(n1, n2))

    def replace(self, prefix, replacement):
        """
        Return a new ``Import`` that replaces ``prefix`` with ``replacement``.

          >>> Import("from aa.bb import cc").replace("aa.bb", "xx.yy")
          Import('from xx.yy import cc')

          >>> Import("from aa import bb").replace("aa.bb", "xx.yy")
          Import('from xx import yy as bb')

        :rtype:
          ``Import``
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
            return CompilerFlags.from_int(0)

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
        if self is other:
            return 0
        if not isinstance(other, Import):
            return NotImplemented
        return cmp(self._data, other._data)

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, Import):
            return NotImplemented
        return self._data == other._data

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if self is other:
            return False
        if not isinstance(other, Import):
            return NotImplemented
        return self._data < other._data


@total_ordering
class ImportStatement(object):
    """
    Token-level representation of an import statement containing multiple
    imports from a single module.  Corresponds to an ``ast.ImportFrom`` or
    ``ast.Import``.
    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonStatement, str)):
            return cls._from_statement(arg)
        if isinstance(arg, (ast.ImportFrom, ast.Import)):
            return cls._from_ast_node(arg)
        if isinstance(arg, Import):
            return cls._from_imports([arg])
        if isinstance(arg, (tuple, list)) and len(arg):
            if isinstance(arg[0], Import):
                return cls._from_imports(arg)
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
    def _from_statement(cls, statement):
        """
          >>> ImportStatement._from_statement("from foo  import bar, bar2, bar")
          ImportStatement('from foo import bar, bar2, bar')

          >>> ImportStatement._from_statement("from foo  import bar as bar")
          ImportStatement('from foo import bar as bar')

          >>> ImportStatement._from_statement("from foo.bar  import baz")
          ImportStatement('from foo.bar import baz')

          >>> ImportStatement._from_statement("import  foo.bar")
          ImportStatement('import foo.bar')

          >>> ImportStatement._from_statement("from .foo  import bar")
          ImportStatement('from .foo import bar')

          >>> ImportStatement._from_statement("from .  import bar, bar2")
          ImportStatement('from . import bar, bar2')

        :type statement:
          `PythonStatement`
        :rtype:
          `ImportStatement`
        """
        statement = PythonStatement(statement)
        return cls._from_ast_node(statement.ast_node)

    @classmethod
    def _from_ast_node(cls, node):
        """
        Construct an `ImportStatement` from an `ast` node.

        :rtype:
          `ImportStatement`
        """
        if isinstance(node, ast.ImportFrom):
            if isinstance(node.module, str):
                module = node.module
            elif node.module is None:
                # In python2.7, ast.parse("from . import blah") yields
                # node.module = None.  In python2.6, it's the empty string.
                module = ''
            else:
                raise TypeError("unexpected node.module=%s"
                                % type(node.module).__name__)
            fromname = '.' * node.level + module
        elif isinstance(node, ast.Import):
            fromname = None
        else:
            raise NonImportStatementError
        aliases = [ (alias.name, alias.asname) for alias in node.names ]
        return cls.from_parts(fromname, aliases)

    @classmethod
    def _from_imports(cls, imports):
        """
        Construct an `ImportStatement` from a sequence of ``Import`` s.  They
        must all have the same ``fromname``.

        :type imports:
          Sequence of `Import` s
        :rtype:
          `ImportStatement`
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
        Return a sequence of `Import` s.

        :rtype:
          ``tuple`` of `Import` s
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

        :type params:
          `FormatParams`
        :param modulename_ljust:
          Number of characters to left-justify the 'from' name.
        :rtype:
          ``str``
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
        res = s0 + pyfill(s, tokens, params=params)
        if params.use_black:
            import black
            mode = black.FileMode()
            return black.format_str(res, mode=mode)
        return res

    @property
    def _data(self):
        return (self.fromname, self.aliases)

    def __str__(self):
        return self.pretty_print(FormatParams(max_line_length=Inf)).rstrip()

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, str(self))

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, ImportStatement):
            return NotImplemented
        return cmp(self._data, other._data)

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, ImportStatement):
            return NotImplemented
        return self._data == other._data

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, ImportStatement):
            return NotImplemented
        return self._data < other._data

    def __hash__(self):
        return hash(self._data)
