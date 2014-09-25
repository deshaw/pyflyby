
from __future__ import absolute_import, division, with_statement

import ast
import copy
import operator
import re

from   itertools                import groupby

from   pyflyby.file             import FileContents, FileLines, Filename
from   pyflyby.flags            import CompilerFlags
from   pyflyby.util             import cached_attribute

def is_comment_or_blank(line):
    """
    Returns whether a line of python code contains only a comment is blank.

      >>> is_comment_or_blank("foo\\n")
      False

      >>> is_comment_or_blank("  # blah\\n")
      True
    """
    return re.sub("#.*", "", line).rstrip() == ""


class MoreThanOneAstNodeError(Exception):
    pass


def _ast_str_literal_value(node):
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
        return node.value.s
    else:
        return None

class _DummyAst_Node(object):
    pass

class PythonFileLines(FileLines):

    def __new__(cls, arg, flags=0):
        result = FileLines.__new__(cls, arg)
        flags = CompilerFlags(flags)
        return result.with_flags(flags)

    @classmethod
    def from_lines(cls, lines, filename=None, linenumber=1, flags=0):
        self = super(cls, PythonFileLines).from_lines(
            lines, filename=filename, linenumber=linenumber)
        self.flags = CompilerFlags(flags)
        return self

    @classmethod
    def from_text(cls, text, linenumber=1, flags=0):
        self = super(cls, PythonFileLines).from_text(
            text, linenumber=linenumber)
        self.flags = CompilerFlags(flags)
        return self

    def with_flags(self, flags):
        if flags == 0:
            return self
        flags = self.flags | CompilerFlags(flags)
        if flags == self.flags:
            return self
        return type(self).from_lines(
            self.lines, filename=self.filename, linenumber=self.linenumber,
            flags=flags)

    @cached_attribute
    def ast_nodes(self):
        # May also be set internally by L{__attach_ast_nodes}
        filename = str(self.filename) if self.filename else "<unknown>"
        text = self.joined
        if not text.endswith("\n"):
            # Ensure that the last line ends with a newline (C{ast} barfs
            # otherwise).
            text += "\n"
        flags = ast.PyCF_ONLY_AST | int(self.flags)
        return compile(text, filename, "exec", flags=flags, dont_inherit=1).body

    @cached_attribute
    def ast(self):
        return ast.Module(self.ast_nodes)

    @cached_attribute
    def annotated_ast_nodes(self):
        """
        Return C{self.ast_nodes} where each node has added attributes
        C{start_lineno} and C{end_lineno}.  end_lineno is 1 after the last
        line number whose source comprises a given node.
        """
        nodes = self.ast_nodes
        # For some crazy reason, lineno represents something different for
        # string literals versus all other statements.  For string literals it
        # represents the last line; for other statements it represents the
        # first line.  E.g. "'''foo\nbar'''" would have a lineno of 2, but
        # "x='''foo\nbar'''" would have a lineno of 1.
        #
        # First, find the start_lineno of each node.  For non-strings it's
        # simply the lineno.  For string literals, we only know that the
        # starting line number is somewhere between the previous node's lineno
        # and this one.  Iterate over each node.  We create a dummy sentinel
        # to serve as the "prev node" of the last first node.
        start_sentinel = _DummyAst_Node()
        start_sentinel.lineno = 0
        for prev_node, node in zip([start_sentinel] + nodes[:-1], nodes):
            s = _ast_str_literal_value(node)
            if s is None:
                # Not a string literal.  Easy.
                node.start_lineno = node.lineno
                continue
            # Node is a string literal expression.  The starting line number
            # of this string could be anywhere between the end of the previous
            # expression (exclusive since assuming no compound statements) and
            # C{lineno}.  Try line by line until we parse it correctly.  Try
            # from the end because we don't want initial comments/etc.
            for start_lineno in xrange(node.lineno, prev_node.lineno, -1):
                sublines = self[start_lineno:node.lineno+1]
                try:
                    nnodes = sublines.ast_nodes
                except SyntaxError:
                    continue
                if len(nnodes) != 1 or _ast_str_literal_value(nnodes[0]) != s:
                    continue
                node.start_lineno = start_lineno
                break
            else:
                raise Exception(
                    "Couldn't find starting line number of string for %r"
                    % (ast.dump(node)))
        # Now that we have correct starting line numbers we can use this to
        # find ending line numbers.  We create a dummy sentinel node to serve
        # as the "next node" of the last node.
        end_sentinel = _DummyAst_Node()
        end_sentinel.start_lineno = self.end_linenumber
        for node, next_node in zip(nodes, nodes[1:] + [end_sentinel]):
            start_lineno = node.start_lineno
            end_lineno = next_node.start_lineno
            if start_lineno == end_lineno:
                # Implementing compound statements (two or more statements
                # separated by ";") is tricky because we'll have to
                # re-architect PythonFileLines.  We'll have to allow "lines"
                # that don't end in a newline, and we'll no longer be able to
                # index/slice by line number.  There's also the question of
                # how to pretty-print this: presumably we'd want to just add
                # newlines before and after import blocks, but not touch
                # non-import blocks.  The strategy for splitting could be to
                # split naively on ';', but check that parsing the parts with
                # C{compile} matches, and if it doesn't (because the ';' is in
                # a string or something), then try the next one.  Since
                # compound statements are rarely used, we punt for now.
                # Note that this only affects top-level compound statements.
                raise NotImplementedError(
                    "Not implemented: parsing of top-level compound statements: "
                    "line %r: %s" % (start_lineno, self[start_lineno]))
            if node.col_offset > 0:
                # col_offset can be -1 for a toplevel docstring
                raise AssertionError(
                    "Shouldn't see col_offset != 0 for top-level "
                    "non-compound statements")
            assert 1 <= start_lineno < end_lineno
            while is_comment_or_blank(self[end_lineno-1]):
                end_lineno -= 1
            assert 1 <= start_lineno < end_lineno
            node.end_lineno = end_lineno
        return nodes


    def __attach_ast_nodes(self, ast_nodes):
        # Used internally to attach C{nodes} as an optimization when we've
        # already parsed a superset of this sequence of file lines.
        assert 'ast_nodes' not in self.__dict__
        self.ast_nodes = ast_nodes
        return self

    @cached_attribute
    def ast_node(self):
        ast_nodes = self.ast_nodes
        if len(ast_nodes) == 0:
            return None
        if len(ast_nodes) == 1:
            return ast_nodes[0]
        raise MoreThanOneAstNodeError()

    def split(self):
        r"""
        Partition this L{PythonFileLines} into smaller L{PythonFileLines}
        instances where each one contains at most 1 top-level ast node.
        Returned L{PythonFileLines} instances can contain no ast nodes if they
        are entirely composed of comments.

          >>> s = "# multiline\n# comment\n'''multiline\nstring'''\nblah\n"
          >>> for l in PythonFileLines(s).split(): print l
          PythonFileLines.from_text('# multiline\n# comment\n', linenumber=1)
          PythonFileLines.from_text("'''multiline\nstring'''\n", linenumber=3)
          PythonFileLines.from_text('blah\n', linenumber=5)

        @rtype:
          Generator that yields L{PythonFileLines} instances.
        """
        ast_nodes = self.annotated_ast_nodes
        if not ast_nodes:
            # Entirely comments/blanks.
            yield self
            return
        if ast_nodes[0].start_lineno > 1:
            # Starting comments/blanks
            yield self[1:ast_nodes[0].start_lineno].__attach_ast_nodes([])
        # Iterate over each ast ast_node.  We create a dummy sentinel ast_node
        # to serve as the "next ast_node" of the last ast_node.
        sentinel = _DummyAst_Node()
        sentinel.start_lineno = self.end_linenumber
        for node, next_node in zip(ast_nodes, ast_nodes[1:] + [sentinel]):
            yield self[node.start_lineno:node.end_lineno] \
                .__attach_ast_nodes([node])
            if node.end_lineno != next_node.start_lineno:
                yield self[node.end_lineno:next_node.start_lineno] \
                    .__attach_ast_nodes([])


class PythonStatement(object):
    """
    Representation of a top-level Python statement or consecutive
    comments/blank lines.

    A statement has a C{flags} attribute that gives the compiler_flags
    associated with the __future__ features in which the statement should be
    interpreted.
    """

    def __new__(cls, arg, flags=0):
        if isinstance(arg, cls):
            return arg.with_flags(flags)
        if isinstance(arg, PythonFileLines):
            return cls.from_lines(arg, flags=flags)
        if isinstance(arg, (FileContents, str)):
            return cls.from_source_code(arg, flags=flags)
        raise TypeError

    def with_flags(self, flags):
        if flags == 0:
            return self
        flags = CompilerFlags(flags, self.flags)
        if flags == self.flags:
            return self
        result = object.__new__(type(self))
        result.lines = self.lines
        result.flags = flags
        return result

    @classmethod
    def from_lines(cls, lines, flags=0):
        """
        @type lines:
          L{PythonFileLines}
        @param lines:
          Lines of code as a single string.  Ends with newline.
        @param node:
          C{ast} node.  If C{None}, then this is a block of comments/blanks.
        """
        lines = PythonFileLines(lines)
        # This will raise MoreThanOneAstNodeError if lines contains more than
        # one AST node:
        lines.ast_node
        self = object.__new__(cls)
        self.lines = lines
        self.flags = self.source_flags | flags
        return self

    @classmethod
    def from_source_code(cls, source_code, flags=0):
        statements = PythonBlock(source_code)
        if len(statements) != 1:
            raise ValueError(
                "Code contains %d statements instead of exactly 1: %r"
                % (len(statements), source_code))
        assert isinstance(statements[0], cls)
        return statements[0].with_flags(flags)

    @property
    def ast_node(self):
        return self.lines.ast_node

    @property
    def is_comment_or_blank(self):
        return self.ast_node is None

    @property
    def is_comment_or_blank_or_string_literal(self):
        return (self.is_comment_or_blank
                or _ast_str_literal_value(self.ast_node) is not None)

    @property
    def is_import(self):
        return isinstance(self.ast_node, (ast.Import, ast.ImportFrom))

    @cached_attribute
    def source_flags(self):
        """
        If this is a __future__ import, then the compiler_flags associated
        with it.  Otherwise, 0.

        The difference between C{source_flags} and C{flags} is that C{flags}
        may be set by the caller based on a previous __future__ import,
        whereas C{source_flags} is only nonzero if this statement itself is a
        __future__ import.

        @rtype:
          L{CompilerFlags}
        """
        node = self.ast_node
        if not isinstance(node, ast.ImportFrom):
            return CompilerFlags(0)
        if not node.module == "__future__":
            return CompilerFlags(0)
        names = [n.name for n in node.names]
        return CompilerFlags(names)

    def __repr__(self):
        return "%s(%r, flags=%s)" % (type(self).__name__, self.lines, self.flags)


class PythonBlock(tuple):
    """
    Representation of a sequence of consecutive top-level
    L{PythonStatement}(s).

      >>> source_code = '# 1\\nprint 2\\n# 3\\n# 4\\nprint 5\\nx=[6,\\n 7]\\n# 8'
      >>> codeblock = PythonBlock(source_code)
      >>> for stmt in PythonBlock(codeblock):
      ...     print stmt
      PythonStatement(PythonFileLines.from_text('# 1\\n', linenumber=1))
      PythonStatement(PythonFileLines.from_text('print 2\\n', linenumber=2))
      PythonStatement(PythonFileLines.from_text('# 3\\n# 4\\n', linenumber=3))
      PythonStatement(PythonFileLines.from_text('print 5\\n', linenumber=5))
      PythonStatement(PythonFileLines.from_text('x=[6,\\n 7]\\n', linenumber=6))
      PythonStatement(PythonFileLines.from_text('# 8', linenumber=8))

    """

    def __new__(cls, arg, flags=0):
        if isinstance(arg, cls):
            return arg.with_flags(flags)
        if isinstance(arg, PythonStatement):
            return cls.from_statements([arg], flags=flags)
        if isinstance(arg, (PythonFileLines, FileContents, Filename, str)):
            return cls.from_lines(arg, flags=flags)
        if isinstance(arg, (list, tuple)) and arg:
            if isinstance(arg[0], PythonStatement):
                return cls.from_statements(arg, flags=flags)
            return cls.from_multiple(arg, flags=flags)
        raise TypeError

    def with_flags(self, flags):
        if flags == 0:
            return self
        flags = CompilerFlags(flags, self.flags)
        if flags == self.flags:
            return self
        return self.from_statements(self, flags=flags)

    @classmethod
    def from_statements(cls, statements, flags=0):
        """
        @rtype:
          L{PythonBlock}
        """
        # Canonicalize statements.
        statements = tuple(PythonStatement(stmt) for stmt in statements)
        # Get the combined compiler_flags at the end of the block.
        flags = CompilerFlags(flags, *[s.flags for s in statements])
        # Make sure all statements have the proper flags attached.
        if flags:
            statements = tuple(stmt.with_flags(flags) for stmt in statements)
        # Construct new object.
        self = tuple.__new__(cls, statements)
        self.flags = flags
        return self

    @classmethod
    def from_lines(cls, lines, flags=0):
        """
        @type lines:
          L{PythonFileLines} or convertible
        @rtype:
          L{PythonBlock}
        """
        lines = PythonFileLines(lines, flags=flags)
        return cls.from_statements(
            [PythonStatement.from_lines(sublines, flags=flags)
             for sublines in lines.split()])

    @classmethod
    def from_multiple(cls, blocks, flags=0):
        """
        Concatenate a bunch of blocks into one block.

        @type blocks:
          Sequence of L{PythonBlock}s
        @rtype:
          L{PythonBlock}
        """
        blocks = [cls(block) for block in blocks]
        if len(blocks) == 1:
            return blocks[0]
        statements = reduce(operator.add, blocks, ())
        flags = CompilerFlags(flags, *[b.flags for b in blocks])
        return cls.from_statements(statements, flags=flags)

    @cached_attribute
    def lines(self):
        return ''.join(stmt.lines.joined for stmt in self)

    @cached_attribute
    def split_lines(self):
        return self.lines.splitlines()

    @cached_attribute
    def linenumber(self):
        return self[0].lines.linenumber

    @cached_attribute
    def end_linenumber(self):
        return self[-1].lines.end_linenumber

    @cached_attribute
    def parse_tree(self):
        """
        Return an C{AST} as returned by the C{compiler} module.
        """
        # Note that the 'compiler' module is deprecated, which is why we use
        # the C{compile} built-in above.  This is for interfacing with
        # pyflakes 0.4 and earlier.
        import compiler
        text = self.lines
        if not text.endswith("\n"):
            # Ensure that the last line ends with a newline (C{parse} barfs
            # otherwise).
            # TODO: instead of appending \n here, make sure the lines end in
            # \n at construction time.
            text += "\n"
        return compiler.parse(text)

    @cached_attribute
    def ast(self):
        """
        Return an C{AST} as returned by the C{compile} built-in.
        """
        return PythonFileLines.from_text(self.lines).ast

    def __repr__(self):
        return "%s(%r, flags=%s)" % (type(self).__name__, self.lines, self.flags)

    def groupby(self, predicate):
        """
        Partition this block of code into smaller blocks of code which
        consecutively have the same C{predicate}.

        @param predicate:
          Function that takes a L{PythonStatement} and returns a value.
        @return:
          Generator that yields (group, L{PythonBlock}s).
        """
        for pred, stmts in groupby(self, predicate):
            yield pred, type(self)(tuple(stmts))

    def string_literals(self):
        """
        Yield all string literals anywhere in C{ast_node}.

          >>> list(PythonBlock("'a' + ('b' + \\n'c')").string_literals())
          [('a', 1), ('b', 1), ('c', 2)]

        @rtype:
          Generator that yields (C{str}, C{int}).
        @return:
          Iterable of string literals and line numbers.
        """
        for statement in self:
            if not statement.ast_node:
                continue
            for node in ast.walk(statement.ast_node):
                for fieldname, field in ast.iter_fields(node):
                    if isinstance(field, ast.Str):
                        yield field.s, field.lineno
