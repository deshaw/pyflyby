
from __future__ import absolute_import, division, with_statement

import ast
import operator
import re

from itertools import groupby

from pyflyby.file import Filename, read_file
from pyflyby.util import cached_attribute

def is_comment_or_blank(line):
    """
    Returns whether a line of python code contains only a comment is blank.

      >>> is_comment_or_blank("foo\\n")
      False

      >>> is_comment_or_blank("  # blah\\n")
      True
    """
    return re.sub("#.*", "", line).rstrip() == ""


class FileLines(object):
    """
    Represents a contiguous sequence of lines from a file.
    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, Filename):
            return cls.from_filename(arg)
        if isinstance(arg, str):
            return cls.from_text(arg)
        raise TypeError

    @classmethod
    def from_lines(cls, lines, filename=None, linenumber=1):
        """
        @type params:
          Sequence of strings, each of which ends with a newline and has no
          other newlines.
        @rtype:
          L{FileLines}
        """
        if isinstance(lines, str):
            raise TypeError
        self = object.__new__(cls)
        self.lines = lines
        self.filename = filename
        self.linenumber = linenumber
        return self

    @classmethod
    def from_text(cls, text, filename=None, linenumber=1):
        # Split into physical lines.
        lines = text.splitlines(True)
        self = cls.from_lines(lines, filename=filename, linenumber=linenumber)
        self.joined = text # optimization
        return self

    @classmethod
    def from_filename(cls, filename, linenumber=1):
        filename = Filename(filename)
        text = read_file(filename)
        if not text.endswith("\n"):
            # Ensure that the last line ends with a newline (C{ast} barfs
            # otherwise).
            text += "\n"
        return cls.from_text(text, filename=filename, linenumber=linenumber)

    @cached_attribute
    def joined(self):
        return ''.join(self.lines)

    @cached_attribute
    def end_linenumber(self):
        """
        The number of the line after the lines contained in self.
        """
        return self.linenumber + len(self.lines)

    def _linenumber_to_index(self, linenumber):
        if not self.linenumber <= linenumber <= self.end_linenumber:
            raise ValueError(
                "Line number %d out of range [%d, %d)"
                % (linenumber, self.linenumber, self.end_linenumber))
        return linenumber - self.linenumber

    def __getitem__(self, arg):
        """
        Return the line(s) with the given line number(s).
        If slicing, returns an instance of C{FileLines}.

        TODO: doctest

        @rtype:
          C{str} or L{FileLines}
        """
        N = self._linenumber_to_index
        if isinstance(arg, slice):
            if arg.step is not None and arg.step != 1:
                raise ValueError("steps not supported")
            return type(self).from_lines(
                self.lines[N(arg.start):N(arg.stop)],
                self.filename, arg.start)
        elif isinstance(arg, int):
            return self.lines[N(arg)]
        else:
            raise TypeError("bad type %r" % (type(arg),))

    def __repr__(self):
        return ("%s.from_text(%r, filename=%r, linenumber=%r)"
                % (type(self).__name__, self.joined,
                   self.filename, self.linenumber))


class MoreThanOneAstNodeError(Exception):
    pass

class PythonFileLines(FileLines):
    @cached_attribute
    def ast_nodes(self):
        # May also be set internally by L{__attach_nodes}
        filename = str(self.filename) if self.filename else "<unknown>"
        return compile(
            self.joined, filename, "exec", ast.PyCF_ONLY_AST, 0).body

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
        """
        Partition this L{PythonFileLines} into smaller L{PythonFileLines}
        instances where each one contains at most 1 ast node.  Returned
        L{PythonFileLines} instances can contain no ast nodes if they are
        entirely composed of comments.

        @rtype:
          Generator that yields L{PythonFileLines} instances.
        """
        ast_nodes = self.ast_nodes
        if not ast_nodes:
            # Entirely comments/blanks.
            yield self
            return
        if ast_nodes[0].lineno > 1:
            # Starting comments/blanks
            yield self[1:ast_nodes[0].lineno].__attach_ast_nodes([])
        # Iterate over each ast ast_node.  We create a dummy sentinel ast_node to
        # serve as the "next ast_node" of the last ast_node.
        class DummyAst_Node(object):
            pass
        sentinel = DummyAst_Node()
        sentinel.lineno = self.end_linenumber
        for node, next_node in zip(ast_nodes, ast_nodes[1:] + [sentinel]):
            linenumber = node.lineno
            end_linenumber = next_node.lineno
            # TODO: this doesn't work correctly with semicolon-delimited
            # compound statements.
            assert 1 <= linenumber < end_linenumber
            while is_comment_or_blank(self[end_linenumber-1]):
                end_linenumber -= 1
            assert 1 <= linenumber < end_linenumber
            yield self[linenumber:end_linenumber].__attach_ast_nodes([node])
            if end_linenumber != next_node.lineno:
                yield self[end_linenumber:next_node.lineno] \
                    .__attach_ast_nodes([])


class PythonStatement(object):
    """
    Representation of a top-level Python statement or consecutive
    comments/blank lines.
    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, PythonFileLines):
            return cls.from_lines(arg)
        if isinstance(arg, str):
            return cls.from_source_code(arg)
        raise TypeError

    @classmethod
    def from_lines(cls, lines):
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
        return self

    @classmethod
    def from_source_code(cls, source_code):
        statements = PythonBlock.from_source_code(source_code)
        if len(statements) != 1:
            raise ValueError(
                "Code contains %d statements instead of exactly 1: %r"
                % (len(statements), source_code))
        return statements[0]

    @property
    def ast_node(self):
        return self.lines.ast_node

    @property
    def is_comment_or_blank(self):
        return self.ast_node is None

    @property
    def is_import(self):
        return isinstance(self.ast_node, (ast.Import, ast.ImportFrom))

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.lines)


class PythonBlock(tuple):
    """
    Representation of a sequence of consecutive top-level
    L{PythonStatement}(s).

      >>> source_code = '# 1\\nprint 2\\n# 3\\n# 4\\nprint 5\\nx=[6,\\n 7]\\n# 8'
      >>> codeblock = PythonBlock(source_code)
      >>> print codeblock[0]
      PythonStatement(PythonFileLines.from_text('# 1\\n', filename=None, linenumber=1))

      >>> for stmt in PythonBlock(codeblock):
      ...     print stmt.lines
      PythonFileLines.from_text('# 1\\n', filename=None, linenumber=1)
      PythonFileLines.from_text('print 2\\n', filename=None, linenumber=2)
      PythonFileLines.from_text('# 3\\n# 4\\n', filename=None, linenumber=3)
      PythonFileLines.from_text('print 5\\n', filename=None, linenumber=5)
      PythonFileLines.from_text('x=[6,\\n 7]\\n', filename=None, linenumber=6)
      PythonFileLines.from_text('# 8', filename=None, linenumber=8)

    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, PythonStatement):
            return cls.from_statements([arg])
        if isinstance(arg, PythonFileLines):
            return cls.from_lines(arg)
        if isinstance(arg, Filename):
            return cls.from_filename(arg)
        if isinstance(arg, str):
            return cls.from_source_code(arg)
        if isinstance(arg, (list, tuple)) and arg:
            if isinstance(arg[0], PythonStatement):
                return cls.from_statements(arg)
            return cls.from_multiple(arg)
        raise TypeError

    @classmethod
    def from_statements(cls, statements):
        statements = tuple(PythonStatement(stmt) for stmt in statements)
        self = tuple.__new__(cls, statements)
        return self

    @classmethod
    def from_lines(cls, lines):
        """
        @type lines:
          L{PythonFileLines} or convertible
        @rtype:
          L{PythonBlock}
        """
        lines = PythonFileLines(lines)
        return cls.from_statements(
            [PythonStatement.from_lines(sublines)
             for sublines in lines.split()])

    @classmethod
    def from_source_code(cls, source_code, filename=None):
        """
        @type lines:
          C{str}
        @rtype:
          L{PythonBlock}
        """
        return cls.from_lines(
            PythonFileLines.from_text(source_code, filename=filename))

    @classmethod
    def from_filename(cls, filename):
        """
        @type lines:
          L{Filename}
        @rtype:
          L{PythonBlock}
        """
        return cls.from_lines(PythonFileLines.from_filename(Filename(filename)))

    @classmethod
    def from_multiple(cls, blocks):
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
        return cls.from_statements(statements)

    @cached_attribute
    def lines(self):
        return ''.join(stmt.lines.joined for stmt in self)

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
        # pyflakes.
        import compiler
        return compiler.parse(self.lines)

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.lines)

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

