
from __future__ import absolute_import, division, with_statement

import ast
from   itertools                import groupby
import re

from   pyflyby.file             import FileText, Filename
from   pyflyby.flags            import CompilerFlags
from   pyflyby.log              import logger
from   pyflyby.util             import cached_attribute

def _is_comment_or_blank(line):
    """
    Returns whether a line of python code contains only a comment is blank.

      >>> _is_comment_or_blank("foo\\n")
      False

      >>> _is_comment_or_blank("  # blah\\n")
      True
    """
    return re.sub("#.*", "", line).rstrip() == ""


def _ast_str_literal_value(node):
    if isinstance(node, ast.Str):
        return node.s
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
        return node.value.s
    else:
        return None


def _compile_ast_nodes(text, flags):
    """
    Parse a block of lines into an AST.

    @type text:
      C{FileText}
    @type flags:
      C{CompilerFlags}
    @rtype:
      C{ast.Module}
    """
    text = FileText(text)
    flags = CompilerFlags(flags)
    filename = str(text.filename) if text.filename else "<unknown>"
    joined = text.joined
    if not joined.endswith("\n"):
        # Ensure that the last line ends with a newline (C{ast} barfs
        # otherwise).
        joined += "\n"
    flags = ast.PyCF_ONLY_AST | int(flags)
    return compile(joined, filename, "exec", flags=flags, dont_inherit=1)


def _compile_annotate_ast_nodes(text, flags):
    """
    Parse a block of lines into an AST and annotate with start_lineno, end_lineno.

    @type text:
      C{FileText}
    @type flags:
      C{CompilerFlags}
    @rtype:
      C{ast.Module}
    """
    text = FileText(text)
    flags = CompilerFlags(flags)
    ast_node = _compile_ast_nodes(text, flags)
    # Annotate starting line numbers.
    # Walk all nodes/fields of the AST.  We implement this as a custom
    # depth-first search instead of using ast.walk() or ast.NodeVisitor
    # so that we can easily keep track of the preceding node's lineno.
    def visit_annotate(prev_lineno, node):
        child_prev_lineno = prev_lineno
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        clineno = visit_annotate(child_prev_lineno, item)
                        child_prev_lineno = max(child_prev_lineno, clineno)
            elif isinstance(value, ast.AST):
                clineno = visit_annotate(child_prev_lineno, value)
                child_prev_lineno = max(child_prev_lineno, clineno)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Str):
            # Optimization: copy the lineno from the Str field instead of
            # redoing the search.
            assert node.lineno == node.value.lineno
            node.start_lineno = node.value.start_lineno
            node.start_colno = node.value.start_colno
        else:
            _annotate_ast_start(node, text, prev_lineno, flags)
        return max(child_prev_lineno, getattr(node, 'lineno', None))
    visit_annotate(text.lineno, ast_node)
    # Now that we have correct starting line numbers we can use this to
    # find ending line numbers.  We create a dummy sentinel node to serve
    # as the "next node" of the last node.
    # We only need this for top-level statements, so only do that for now,
    # rather than recursively traversing the AST.
    end_sentinel = _DummyAst_Node()
    end_sentinel.start_lineno = text.end_lineno
    nodes = ast_node.body
    for node, next_node in zip(nodes, nodes[1:] + [end_sentinel]):
        start_lineno = node.start_lineno
        end_lineno = next_node.start_lineno
        if start_lineno == end_lineno:
            # Implementing compound statements (two or more statements
            # separated by ";") is tricky; we'll have to refactor.  We'll
            # have to allow "lines" that don't end in a newline, and we'll
            # no longer be able to index/slice by line number.  There's
            # also the question of how to pretty-print this: presumably
            # we'd want to just add newlines before and after import
            # blocks, but not touch non-import blocks.  The strategy for
            # splitting could be to split naively on ';', but check that
            # parsing the parts with C{compile} matches, and if it doesn't
            # (because the ';' is in a string or something), then try the
            # next one.  Since compound statements are not often used, we
            # punt for now.  Note that this only affects top-level
            # compound statements.
            raise NotImplementedError(
                "Not implemented: parsing of top-level compound statements: "
                "line %r: %s" % (start_lineno, text[start_lineno]))
        assert node.start_colno == 1, \
            "Expected no indentation for top-level (non-compound) statement"
        assert text.lineno <= start_lineno < end_lineno <= text.end_lineno
        while _is_comment_or_blank(text[end_lineno-1]):
            end_lineno -= 1
        assert start_lineno < end_lineno
        node.end_lineno = end_lineno
    return ast_node


def _annotate_ast_start(ast_node, text, min_start_lineno, flags):
    """
    Annotate C{ast_node} with the starting line number and column number,
    assigning C{ast_node.start_lineno} and C{ast_node.start_colno}.

    For non-string nodes, start_lineno is the same as C{ast_node.lineno}, but
    taking C{text.lineno} into account).  start_colno is col_offset+1.

    For string nodes, this function works by trying to parse all possible
    subranges of lines until finding the range that is syntactically valid and
    matches C{value}.  The candidate range is
    text[min_start_lineno:lineno+text.lineno+1].

    This function is necessary because of a quirk in the output produced by
    the Python built-in compiler.  For some crazy reason, the C{lineno}
    attribute represents something different for string literals versus all
    other statements.  For string nodes and statements that are just a string
    expression, the compiler attaches the ending line number as the value of
    the C{lineno} attribute.  For all other than AST nodes, the compiler
    attaches the starting line number as the value of the C{lineno} attribute.
    This means e.g. the statement "'''foo\nbar'''" has a lineno value of 2,
    but the statement "x='''foo\nbar'''" has a lineno value of 1.

    @type ast_node:
      C{ast.AST}
    @type text:
      C{FileText}
    @param text:
      C{FileText} that was used to compile the AST, whose C{lineno} should be
      used in interpreting C{ast_node.lineno} (which always starts at 1 for
      the subset that was compiled).
    @param min_start_lineno:
      Earliest line number to check, in the number space of C{text}.
    @type flags:
      C{CompilerFlags}
    @param flags:
      Compiler flags to use when re-compiling code.
    @return:
      (start_lineno, start_colno)
    @raise ValueError:
      Could not find the starting line number.
    """
    # Check whether this is a string node or a lone expression for a string.
    s = _ast_str_literal_value(ast_node)
    if s is None:
        # Not a string literal node or statement.  Easy.
        if not hasattr(ast_node, 'lineno'):
            # No lineno, so skip.
            # This should only happen for nodes we don't care about.
            return
        ast_node.start_lineno = ast_node.lineno + text.lineno - 1
        if ast_node.col_offset >= 0:
            ast_node.start_colno = ast_node.col_offset + 1
        else:
            ast_node.start_colno = None
        return
    if ast_node.col_offset >= 0:
        # Not a multiline string literal.  Easy.
        ast_node.start_lineno = ast_node.lineno + text.lineno - 1
        ast_node.start_colno = ast_node.col_offset + 1
        return
    end_lineno = ast_node.lineno + text.lineno - 1
    # Node is a multiline string literal expression.  The starting line number
    # of this string could be anywhere between the end of the previous
    # expression and C{lineno}.  Try line by line until we parse it correctly.
    candidate_start_linenos = range(min_start_lineno, end_lineno + 1)
    # Try from the end because we don't want initial comments/etc.
    # First, look for the exact character the string ends on (using 1-based
    # indexing to be consistent with col_offset indexing), in case the line
    # contains other things (including possibly other strings).
    end_line = text[end_lineno]
    end_line_colno = (text.colno if end_lineno==text.lineno else 1)
    candidate_ends = [(m.group(), m.start()+end_line_colno)
                      for m in re.finditer("[\"\']", end_line)]
    assert candidate_ends, "No quote char found on line with supposed string"
    for quotechar, end_colno in reversed(candidate_ends):
        for start_lineno in reversed(candidate_start_linenos):
            start_line = text[start_lineno]
            start_line_colno = (text.colno if start_lineno==text.lineno else 1)
            candidate_start_colnos = [
                m.start()+start_line_colno
                for m in re.finditer("[bBrRuU]*" + quotechar, start_line)]
            for start_colno in reversed(candidate_start_colnos):
                if start_lineno == end_lineno and start_colno == end_colno:
                    continue
                subtext = text[
                    (start_lineno, start_colno) : (end_lineno, end_colno+1) ]
                try:
                    nnodes = _compile_ast_nodes(subtext, flags).body
                except SyntaxError:
                    continue
                if len(nnodes) != 1 or _ast_str_literal_value(nnodes[0]) != s:
                    continue
                # Success!
                ast_node.start_lineno = start_lineno
                ast_node.start_colno = start_colno
                return
    raise ValueError(
        "Couldn't find starting line number of string for %r"
        % (ast.dump(ast_node)))



class _DummyAst_Node(object):
    pass


class PythonStatement(object):
    r"""
    Representation of a top-level Python statement or consecutive
    comments/blank lines.

      >>> PythonStatement('print("x",\n file=None)\n', flags=0x10000)
      PythonStatement('print("x",\n file=None)\n', flags=0x10000)

    Implemented as a wrapper around a L{PythonBlock} containing at most one
    top-level AST node.
    """

    def __new__(cls, arg, filename=None, lineno=None, flags=None):
        if isinstance(arg, cls):
            if filename is lineno is flags is None:
                return arg
            arg = arg.block
            # Fall through
        if isinstance(arg, (PythonBlock, FileText, str)):
            block = PythonBlock(arg, filename=filename,
                                lineno=lineno, flags=flags)
            statements = block.statements
            if len(statements) != 1:
                raise ValueError(
                    "Code contains %d statements instead of exactly 1: %r"
                    % (len(statements), block))
            statement, = statements
            assert isinstance(statement, cls)
            return statement
        raise TypeError("PythonStatement: unexpected %s" % (type(arg).__name__,))

    @classmethod
    def _construct_from_block(cls, block):
        # Only to be used by PythonBlock.
        assert isinstance(block, PythonBlock)
        self = object.__new__(cls)
        self.block = block
        return self

    @property
    def text(self):
        """
        @rtype:
          L{FileText}
        """
        return self.block.text

    @property
    def filename(self):
        """
        @rtype:
          L{Filename}
        """
        return self.block.filename

    @property
    def lineno(self):
        """
        @rtype:
          C{int}
        """
        return self.block.lineno

    @property
    def flags(self):
        """
        @rtype:
          L{CompilerFlags}
        """
        return self.block.flags

    @property
    def ast_node(self):
        """
        A single AST node representing this statement, or C{None} if this
        object only represents comments/blanks.

        @rtype:
          C{ast.AST} or C{NoneType}
        """
        ast_nodes = self.block.ast_node.body
        if len(ast_nodes) == 0:
            return None
        if len(ast_nodes) == 1:
            return ast_nodes[0]
        raise AssertionError("More than one AST node in block")

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

    def __repr__(self):
        r = repr(self.block)
        assert r.startswith("PythonBlock(")
        r = "PythonStatement(" + r[12:]
        return r


class PythonBlock(object):
    r"""
    Representation of a sequence of consecutive top-level
    L{PythonStatement}(s).

      >>> source_code = '# 1\nprint 2\n# 3\n# 4\nprint 5\nx=[6,\n 7]\n# 8\n'
      >>> codeblock = PythonBlock(source_code)
      >>> for stmt in PythonBlock(codeblock).statements:
      ...     print stmt
      PythonStatement('# 1\n')
      PythonStatement('print 2\n', lineno=2)
      PythonStatement('# 3\n# 4\n', lineno=3)
      PythonStatement('print 5\n', lineno=5)
      PythonStatement('x=[6,\n 7]\n', lineno=6)
      PythonStatement('# 8\n', lineno=8)

    A C{PythonBlock} has a C{flags} attribute that gives the compiler_flags
    associated with the __future__ features using which the code should be
    compiled.

    """

    def __new__(cls, arg, filename=None, lineno=None, flags=None):
        if isinstance(arg, PythonStatement):
            arg = arg.block
            # Fall through
        if isinstance(arg, cls):
            if filename is lineno is flags is None:
                return arg
            return cls.from_text(
                arg.text, filename=filename, lineno=lineno,
                flags=CompilerFlags(flags, arg.flags))
        if isinstance(arg, (FileText, Filename, str)):
            return cls.from_text(arg, filename=filename,
                                 lineno=lineno, flags=flags)
        raise TypeError("%s: unexpected %s"
                        % (cls.__name__, type(arg).__name__,))

    @classmethod
    def from_filename(cls, filename):
        return cls.from_text(Filename(filename))

    @classmethod
    def from_text(cls, text, filename=None, lineno=None, flags=None):
        """
        @type text:
          L{FileText} or convertible
        @rtype:
          L{PythonBlock}
        """
        text = FileText(text, filename=filename, lineno=lineno)
        self = object.__new__(cls)
        self.text = text
        self._input_flags = CompilerFlags(flags)
        return self

    @classmethod
    def __construct_from_text_ast(cls, text, ast_node, flags):
        # Constructor for internal use by _split_by_statement() or
        # concatenate().
        self = object.__new__(cls)
        self.text     = text
        self.ast_node = ast_node
        self.flags    = self._input_flags = flags
        return self

    @classmethod
    def concatenate(cls, blocks, assume_contiguous=False):
        """
        Concatenate a bunch of blocks into one block.

        @type blocks:
          sequence of L{PythonBlock}s and/or L{PythonStatement}s
        @param assume_contiguous:
          Whether to assume, without checking, that the input blocks were
          originally all contiguous.  This must be set to True to indicate the
          caller understands the assumption; False is not implemented.
        """
        if not assume_contiguous:
            raise NotImplementedError
        blocks = [PythonBlock(b) for b in blocks]
        if len(blocks) == 1:
            return blocks[0]
        assert blocks
        text = FileText.concatenate([b.text for b in blocks])
        # The contiguous assumption is important here because C{ast_node}
        # contains line information that would otherwise be wrong.
        ast_node = ast.Module([n for b in blocks for n in b.ast_node.body])
        flags = blocks[0].flags
        return cls.__construct_from_text_ast(text, ast_node, flags)

    @property
    def filename(self):
        return self.text.filename

    @property
    def lineno(self):
        return self.text.lineno

    @property
    def end_lineno(self):
        return self.text.end_lineno

    @cached_attribute
    def ast_node(self):
        """
        Return abstract syntax tree for this block of code.

        The returned object type is the kind of AST as returned by the
        C{compile} built-in (rather than as returned by the older, deprecated
        C{compiler} module).

        The nodes are annotated with C{start_lineno} and C{end_lineno}.

        The result is a C{ast.Module} node, even if this block represents only
        a subset of the entire file.

        @rtype:
          C{ast.Module}
        """
        # ast_node may also be set directly by __construct_from_text_ast(),
        # in which case this code does not run.
        return _compile_annotate_ast_nodes(self.text, self._input_flags)

    def _split_by_statement(self):
        """
        Partition this C{PythonBlock} into smaller C{PythonBlock}s, each of
        which represent either one top-level statement or comments/blanks.
        Each one contains at most 1 top-level ast node.

        @rtype:
          generator of C{PythonBlock}s
        """
        ast_nodes = self.ast_node.body
        text = self.text
        if not ast_nodes:
            # Entirely comments/blanks.
            yield self
            return
        cls = type(self)
        def build(text, ast_nodes):
            ast_node = ast.Module(ast_nodes)
            return cls.__construct_from_text_ast(text, ast_node, self.flags)
        if ast_nodes[0].start_lineno > text.lineno:
            # Starting comments/blanks
            yield build(
                text[text.lineno:ast_nodes[0].start_lineno], [])
        # Iterate over each ast ast_node.  We create a dummy sentinel ast_node
        # to serve as the "next ast_node" of the last ast_node.
        sentinel = _DummyAst_Node()
        sentinel.start_lineno = text.end_lineno
        for node, next_node in zip(ast_nodes, ast_nodes[1:] + [sentinel]):
            # Yield a regular block
            yield build(
                text[node.start_lineno:node.end_lineno], [node])
            if node.end_lineno != next_node.start_lineno:
                # Yield a block with comments/blanks
                yield build(
                    text[node.end_lineno:next_node.start_lineno], [])

    @cached_attribute
    def statements(self):
        r"""
        Partition of this C{PythonBlock} into individual C{PythonStatement}s.
        Each one contains at most 1 top-level ast node.  A C{PythonStatement}
        can contain no ast node to represent comments.

          >>> code = "# multiline\n# comment\n'''multiline\nstring'''\nblah\n"
          >>> print PythonBlock(code).statements
          (PythonStatement('# multiline\n# comment\n'),
           PythonStatement("'''multiline\nstring'''\n", lineno=3)
           PythonStatement('blah\n', lineno=5))

        @rtype:
          C{tuple} of L{PythonStatement}s
        """
        return tuple(PythonStatement._construct_from_block(b)
                     for b in self._split_by_statement())

    @cached_attribute
    def source_flags(self):
        """
        If the AST contains __future__ imports, then the compiler_flags
        associated with them.  Otherwise, 0.

        The difference between C{source_flags} and C{flags} is that C{flags}
        may be set by the caller (e.g. based on an earlier __future__ import),
        whereas C{source_flags} is only nonzero if this code itself contains
        __future__ imports.

        @rtype:
          L{CompilerFlags}
        """
        return CompilerFlags.from_ast(self.ast_node)

    @cached_attribute
    def flags(self):
        """
        The compiler flags for this code block, including both the input flags
        and the source flags.

        @rtype:
          L{CompilerFlags}
        """
        return self._input_flags | self.source_flags

    @cached_attribute
    def parse_tree(self):
        """
        Return an C{AST} as returned by the C{compiler} module.
        """
        # Note that the 'compiler' module is deprecated, which is why we use
        # the C{compile} built-in above.  This is for interfacing with
        # pyflakes 0.4 and earlier.
        import compiler
        joined = self.text.joined
        if not joined.endswith("\n"):
            # Ensure that the last line ends with a newline (C{parse} barfs
            # otherwise).
            # TODO: instead of appending \n here, make sure the lines end in
            # \n at construction time.
            joined += "\n"
        return compiler.parse(joined)

    def __repr__(self):
        r = "%s(%r" % (type(self).__name__, self.text.joined)
        if self.filename:
            r += ", filename=%r" % (str(self.filename),)
        if self.lineno != 1:
            r += ", lineno=%r" % (self.lineno,)
        if self.flags != self.source_flags:
            r += ", flags=%s" % (self.flags,)
        r += ")"
        return r

    def groupby(self, predicate):
        """
        Partition this block of code into smaller blocks of code which
        consecutively have the same C{predicate}.

        @param predicate:
          Function that takes a L{PythonStatement} and returns a value.
        @return:
          Generator that yields (group, L{PythonBlock}s).
        """
        cls = type(self)
        for pred, stmts in groupby(self.statements, predicate):
            blocks = [s.block for s in stmts]
            yield pred, cls.concatenate(blocks, assume_contiguous=True)

    def string_literals(self):
        r"""
        Yield all string literals anywhere in this block.

          >>> [(f.s, f.start_lineno) for f in PythonBlock("'a' + ('b' + \n'c')").string_literals()]
          [('a', 1), ('b', 1), ('c', 2)]

        @return:
          Iterable of C{ast.Str} nodes
        """
        for node in ast.walk(self.ast_node):
            for fieldname, field in ast.iter_fields(node):
                if isinstance(field, ast.Str):
                    assert hasattr(field, 'start_lineno')
                    yield field

    def get_doctests(self):
        r"""
        Return doctests in this code.

          >>> PythonBlock("x\n'''\n >>> foo(bar\n ...     + baz)\n'''\n").get_doctests()
          [PythonBlock('foo(bar\n    + baz)\n', lineno=3)]

        @rtype:
          C{list} of L{PythonStatement}s
        """
        import doctest
        parser = doctest.DocTestParser()
        doctest_blocks = []
        filename = self.filename
        flags = self.flags
        for ast_node in self.string_literals():
            try:
                examples = parser.get_examples(ast_node.s)
            except Exception:
                blob = ast_node.s
                if len(blob) > 60:
                    blob = blob[:60] + '...'
                # TODO: let caller decide how to handle
                logger.warning("Can't parse docstring; ignoring: %r", blob)
                continue
            for example in examples:
                lineno = ast_node.start_lineno + example.lineno
                colno = ast_node.start_colno + example.indent # dubious
                text = FileText(example.source, filename=filename,
                                lineno=lineno, colno=colno)
                try:
                    block = PythonBlock(text, flags=flags)
                except Exception:
                    blob = text.joined
                    if len(blob) > 60:
                        blob = blob[:60] + '...'
                    logger.warning("Can't parse doctest; ignoring: %r", blob)
                    continue
                doctest_blocks.append(block)
        return doctest_blocks


    def __text__(self):
        return self.text
