# pyflyby/_importstmt.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



import ast
from   collections              import namedtuple
from   functools                import total_ordering

from   pyflyby._flags           import CompilerFlags
from   pyflyby._format          import FormatParams, pyfill
from   pyflyby._idents          import is_identifier
from   pyflyby._parse           import PythonStatement
from   pyflyby._util            import (Inf, cached_attribute, cmp,
                                        longest_common_prefix)


from   typing                   import Dict, Optional, Tuple, Union



def read_black_config() -> Dict:
    """Read the black configuration from ``pyproject.toml``"""
    from black.files import find_pyproject_toml, parse_pyproject_toml

    pyproject_path = find_pyproject_toml((".",))

    raw_config = parse_pyproject_toml(pyproject_path) if pyproject_path else {}

    config = {}
    for key in [
        "line_length",
        "skip_magic_trailing_comma",
        "skip_string_normalization",
    ]:
        if key in raw_config:
            config[key] = raw_config[key]
    if "target_version" in raw_config:
        target_version = raw_config["target_version"]
        if isinstance(target_version, str):
            config["target_version"] = target_version
        elif isinstance(target_version, list):
            # Convert TOML list to a Python set
            config["target_version"] = set(target_version)
        else:
            raise ValueError(
                f"Invalid config for black = {target_version!r} in {pyproject_path}"
            )
    return config


class ImportFormatParams(FormatParams):
    align_imports:Union[bool, set, list, tuple, str] = True
    """
    Whether and how to align 'from modulename import aliases...'.  If ``True``,
    then the 'import' keywords will be aligned within a block.  If an integer,
    then the 'import' keyword will always be at that column.  They will be
    wrapped if necessary.
    """

    from_spaces:int = 1
    """
    The number of spaces after the 'from' keyword.  (Must be at least 1.)
    """

    separate_from_imports:bool = True
    """
    Whether all 'from ... import ...' in an import block should come after
    'import ...' statements.  ``separate_from_imports = False`` works well with
    ``from_spaces = 3``.  ('from __future__ import ...' always comes first.)
    """

    align_future:bool = False
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
class Import:
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

    fullname:str
    import_as:str
    comment: Optional[str] = None

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
    def from_parts(cls, fullname, import_as, comment=None):
        assert isinstance(fullname, str)
        assert isinstance(import_as, str)
        self = object.__new__(cls)
        self.fullname = fullname
        self.import_as = import_as
        self.comment = comment
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
    def from_split(cls, impsplit, comment=None):
        """
        Construct an `Import` instance from ``module_name``, ``member_name``,
        ``import_as``.

        :rtype:
          `Import`
        """
        module_name, member_name, import_as = ImportSplit(*impsplit)
        if import_as is None:
            import_as = member_name
        if module_name is None:
            result = cls.from_parts(member_name, import_as, comment)
        else:
            fullname = "%s%s%s" % (
                module_name,
                "" if module_name.endswith(".") else ".",
                member_name)
            result = cls.from_parts(fullname, import_as, comment)
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

def _validate_alias(arg) -> Tuple[str, Optional[str]]:
    """
    Ensure each alias is a tuple (str, None|str), and return it.

    """
    assert isinstance(arg, tuple)
    # Pyright does not seem to be able to infer the length from a
    # the unpacking.
    assert len(arg) == 2
    a0, a1 = arg
    assert isinstance(a0, str)
    assert isinstance(a1, (str, type(None)))
    return arg

@total_ordering
class ImportStatement:
    """
    Token-level representation of an import statement containing multiple
    imports from a single module.  Corresponds to an ``ast.ImportFrom`` or
    ``ast.Import``.
    """

    aliases : Tuple[Tuple[str, Optional[str]],...]
    fromname : Optional[str]
    comments : Optional[list[Optional[str]]] = None

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, str):
            return cls._from_str(arg)
        if isinstance(arg, PythonStatement):
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
    def from_parts(
        cls,
        fromname: Optional[str],
        aliases: Tuple[Tuple[str, Optional[str]], ...],
        comments: Optional[list[Optional[str]]] = None,
    ):
        assert isinstance(aliases, tuple)
        assert len(aliases) > 0

        self = object.__new__(cls)
        self.fromname = fromname
        self.aliases = tuple(_validate_alias(a) for a in aliases)
        self.comments = comments
        return self

    @classmethod
    def _from_str(cls, code:str, /):
        """
          >>> ImportStatement._from_str("from foo  import bar, bar2, bar")
          ImportStatement('from foo import bar, bar2, bar')

          >>> ImportStatement._from_str("from foo  import bar as bar")
          ImportStatement('from foo import bar as bar')

          >>> ImportStatement._from_str("from foo.bar  import baz")
          ImportStatement('from foo.bar import baz')

          >>> ImportStatement._from_str("import  foo.bar")
          ImportStatement('import foo.bar')

          >>> ImportStatement._from_str("from .foo  import bar")
          ImportStatement('from .foo import bar')

          >>> ImportStatement._from_str("from .  import bar, bar2")
          ImportStatement('from . import bar, bar2')

        :type statement:
          `PythonStatement`
        :rtype:
          `ImportStatement`
        """
        return cls._from_statement(
            PythonStatement(code)
        )

    @classmethod
    def _from_statement(cls, statement):
        stmt = PythonStatement.from_statement(statement)
        return cls._from_ast_node(
            stmt.ast_node,
            comments=stmt.text.get_comments()
        )

    @classmethod
    def _from_ast_node(cls, node, comments: Optional[list[Optional[str]]] = None):
        """
        Construct an `ImportStatement` from an `ast` node.

        :rtype:
          `ImportStatement`
        """
        if isinstance(node, ast.ImportFrom):
            if node.module is None:
                module = ''
            else:
                assert isinstance(node.module, str)
                module = node.module
            fromname = '.' * node.level + module
        elif isinstance(node, ast.Import):
            fromname = None
        else:
            raise NonImportStatementError(
                    'Expected ImportStatement, got {node}'.format(node=node)
                    )
        aliases = tuple( (alias.name, alias.asname) for alias in node.names )
        return cls.from_parts(fromname, aliases, comments)

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
            raise ValueError(
                "Inconsistent module names %r" % (sorted(module_names),))

        return cls.from_parts(
            fromname=list(module_names)[0],
            aliases=tuple(imp.split[1:] for imp in imports),
            comments=[imp.comment for imp in imports]
        )

    @cached_attribute
    def imports(self):
        """
        Return a sequence of `Import` s.

        If the returned sequence of imports has only one entry, any single line
        comment will be included with it. Otherwise, line comments are not included
        because there's too much ambiguity about where they should be placed otherwise.

        :rtype:
          ``tuple`` of `Import` s
        """
        result = []
        for alias in self.aliases:
            result.append(
                Import.from_split(
                    (self.fromname, alias[0], alias[1]),
                    comment=self.get_valid_comment(),
                )
            )
        return tuple(result)

    def get_valid_comment(self):
        """Get the comment for the ImportStatment, if possible.

        A comment is only valid if there is a single comment.

        # 1. The ImportStatement has a single alias
        # 2. There is a single string comment in self.comments

        :rtype:
            ``Optional[str]`` containing the valid comment, if any
        """
        if self.comments and len(self.aliases) == 1:
            valid = [comment for comment in self.comments if comment is not None]
            if len(valid) == 1:
                return valid[0]
        return None

    @property
    def module(self) -> Tuple[str, ...]:
        """

        return the import module as a list of string (which would be joined by
        dot in the original import form.

        This is useful for sorting purposes

        Note that this may contain some empty string in particular with relative
        imports
        """
        if self.fromname:
            return tuple(self.fromname.split('.'))


        assert len(self.aliases) == 1, self.aliases

        return tuple(self.aliases[0][0].split('.'))


    def _cmp(self):
        """
        Comparison function for sorting.

        We want to sort:
            - by the root module
            - whether it is an "import ... as", or "from ... import as" import
            - then lexicographically

        """
        return (self.module[0], 0 if self.fromname is not None else 1, self.fromname)

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

        ImportStatement objects represent python import statements, which can span
        multiple lines or multiple aliases. Here we append comments

        - If the output is one line
        - If there is only one comment

        This way we avoid worrying about combining comments from multiple lines,
        or where to place comments if the resulting output is more than one line

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

        comment = self.get_valid_comment()
        if comment is not None:
            # Only append to text on the first line
            lines = res.split('\n')
            if len(lines) == 2:
                lines[0] += f" #{comment}"
                res = "\n".join(lines)

        if params.use_black:
            res = self.run_black(res, params)

        return res

    @staticmethod
    def run_black(src_contents: str, params:FormatParams) -> str:
        """Run the black formatter for the Python source code given as a string

        This is adapted from https://github.com/akaihola/darker

        """
        from black import format_str, FileMode
        from black.mode import TargetVersion

        black_config = read_black_config()
        mode = dict()

        if params.max_line_length is None:
            mode["line_length"] = black_config.get("line_length", params.max_line_length_default)
        else:
            mode["line_length"] = params.max_line_length

        if "target_version" in black_config:
            if isinstance(black_config["target_version"], set):
                target_versions_in = black_config["target_version"]
            else:
                target_versions_in = {black_config["target_version"]}
            all_target_versions = {
                tgt_v.name.lower(): tgt_v for tgt_v in TargetVersion
            }
            bad_target_versions = target_versions_in - set(all_target_versions)
            if bad_target_versions:
                raise ValueError(
                    f"Invalid target version(s) {bad_target_versions}"
                )
            mode["target_versions"] = {
                all_target_versions[n] for n in target_versions_in
            }
        if "skip_magic_trailing_comma" in black_config:
            mode["magic_trailing_comma"] = not black_config[
                "skip_magic_trailing_comma"
            ]
        if "skip_string_normalization" in black_config:
            # The ``black`` command line argument is
            # ``--skip-string-normalization``, but the parameter for
            # ``black.Mode`` needs to be the opposite boolean of
            # ``skip-string-normalization``, hence the inverse boolean
            mode["string_normalization"] = not black_config["skip_string_normalization"]

        # The custom handling of empty and all-whitespace files below will be unnecessary if
        # https://github.com/psf/black/pull/2484 lands in Black.
        contents_for_black = src_contents
        return format_str(contents_for_black, mode=FileMode(**mode))

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
