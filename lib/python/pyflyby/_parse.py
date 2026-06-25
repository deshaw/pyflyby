# pyflyby/_parse.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT
"""
Python parsing utilities for pyflyby.

This module provides AST parsing and manipulation functionality. It includes
PythonBlock and PythonStatement classes for working with Python code.

On newer versions of Python it is suggested to run

    python -m pyflyby.check_parse <path/to/cpython>

This will parse all Python files in the given path and report any parsing issues
"""

from __future__ import annotations, print_function

import ast
from   ast                      import AsyncFunctionDef, TypeIgnore

from   doctest                  import DocTestParser
from   functools                import cached_property, total_ordering
from   itertools                import groupby

from   pyflyby._file            import FilePos, FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._log             import logger
from   pyflyby._util            import cmp

import re
import sys
from   textwrap                 import dedent
from   types                    import NoneType
from   typing                   import (Any, Callable, Dict, Generator,
                                        Iterable, Iterator, List, Literal,
                                        Optional, TYPE_CHECKING, Tuple, Union,
                                        cast)
import warnings

if TYPE_CHECKING:
    from types import CodeType


_sentinel = object()


def _is_comment_or_blank(line: Any, /) -> bool:
    """
    Returns whether a line of python code contains only a comment is blank.

      >>> _is_comment_or_blank("foo\\n")
      False

      >>> _is_comment_or_blank("  # blah\\n")
      True
    """
    return re.sub("#.*", "", line).rstrip() == ""


def _is_ast_str_or_byte(node: Any) -> bool:
    """
    utility function that test if node is an ast.Str|ast.Bytes in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    return _is_ast_str(node) or _is_ast_bytes(node)

def _is_ast_bytes(node: Any) -> bool:
    """
    utility function that test if node is an ast.Str in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    if sys.version_info < (3,12):
        return isinstance(node, ast.Bytes)
    else:
        return (isinstance(node, ast.Constant) and isinstance(node.value , bytes))


def _is_ast_str(node: Any) -> bool:
    """
    utility function that test if node is an ast.Str in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    if sys.version_info < (3,12):
        return isinstance(node, ast.Str)
    else:
        return (isinstance(node, ast.Constant) and isinstance(node.value , str))

def _ast_str_literal_value(node: Any) -> Any:
    if _is_ast_str_or_byte(node):
        return node.s
    if isinstance(node, ast.Expr) and _is_ast_str_or_byte(node.value):
        return node.value.value  # type: ignore[attr-defined]
    else:
        return None


def _parse_ast_nodes(
    text: FileText, flags: Any, mode: str
) -> AnnotatedModule:
    """
    Parse a block of lines into an AST.

    Also annotate ``input_flags``, ``source_flags``, and ``flags`` on the
    resulting ast node.

    :type text:
      ``FileText``
    :type flags:
      ``CompilerFlags``
    :param mode:
      Compilation mode: "exec", "single", or "eval".
    :rtype:
      ``ast.Module``
    """
    assert isinstance(text, FileText)
    filename = str(text.filename) if text.filename else "<unknown>"
    source = dedent(text.joined)
    if not source.endswith("\n"):
        # Ensure that the last line ends with a newline (``ast`` barfs
        # otherwise).
        source += "\n"
    flags = CompilerFlags(flags)
    if re.search(r"# *type:", source):
        # Honor PEP 484 type comments if any appear to be present.
        flags = flags | CompilerFlags('type_comments')
    result = compile(
        source, filename, mode,
        flags=ast.PyCF_ONLY_AST | int(flags), dont_inherit=True)
    # Attach flags to the result.
    result.input_flags = flags
    result.source_flags = CompilerFlags.from_ast(result)
    result.flags = result.input_flags | result.source_flags
    result.text = text
    return result



def _test_parse_string_literal(text: str, flags: Any) -> Any:
    r"""
    Attempt to parse ``text``.  If it parses cleanly to a single string
    literal, return its value.  Otherwise return ``None``.

      >>> _test_parse_string_literal(r'"foo\n" r"\nbar"', None)
      'foo\n\\nbar'

    """
    filetext = FileText(text)
    try:
        module_node = _parse_ast_nodes(filetext, flags, "eval")
    except SyntaxError:
        return None
    body = module_node.body
    if not _is_ast_str_or_byte(body):
        return None
    return body.value  # type: ignore[attr-defined]


def _annotate_ast_nodes(ast_node: ast.AST) -> AnnotatedAst:
    r"""
    Annotate every node in the tree rooted at ``ast_node`` with ``startpos``
    and ``endpos`` attributes giving the node's start and end `FilePos` within
    the source ``text``.

    Since Python 3.8 the built-in parser reports correct ``lineno``/
    ``col_offset`` and ``end_lineno``/``end_col_offset`` for every node --
    including multiline string literals, which historically misreported their
    position as the *ending* line with a ``col_offset`` of -1 -- so positions
    can be read directly off each node rather than reconstructed by re-parsing
    candidate sub-ranges.

    :type ast_node:
      ``ast.AST``
    :param ast_node:
      AST node returned by `_parse_ast_nodes`
    :rtype:
      ``ast.AST``
    """
    aast_node: AnnotatedAst = cast(AnnotatedAst, ast_node)
    startpos = aast_node.text.startpos
    for node in ast.walk(aast_node):
        # ``ast.Module`` and a handful of others carry no position; skip them.
        if not hasattr(node, "lineno") or isinstance(node, TypeIgnore):
            continue
        if (
            isinstance(node, (ast.FunctionDef, ast.ClassDef, AsyncFunctionDef))
            and node.decorator_list
        ):
            # ``lineno`` points at the ``def``/``class`` keyword; back up to the
            # first decorator so the node's text includes its decorators.  The
            # decorator's ``col_offset`` doesn't include the leading ``@``.
            first = node.decorator_list[0]
            delta = (first.lineno - 1, first.col_offset - 1)
        else:
            delta = (node.lineno - 1, node.col_offset)  # type: ignore[attr-defined]
        node.startpos = startpos + delta  # type: ignore[attr-defined]
        if node.end_lineno is not None:  # type: ignore[attr-defined]
            node.endpos = startpos + (node.end_lineno - 1, node.end_col_offset)  # type: ignore[attr-defined]
    return aast_node


def _split_code_lines(
    ast_nodes: Any, text: FileText
) -> Iterator[Tuple[List[Any], Any]]:
    """
    Split the given ``ast_nodes`` and corresponding ``text`` by code/noncode
    statement.

    Yield tuples of (nodes, subtext).  ``nodes`` is a list of ``ast.AST`` nodes,
    length 0 or 1; ``subtext`` is a `FileText` sliced from ``text``.

    FileText(...))} for code lines and ``(None, FileText(...))`` for non-code
    lines (comments and blanks).

    :type ast_nodes:
      sequence of ``ast.AST`` nodes
    :type text:
      `FileText`
    """
    if not ast_nodes:
        yield ([], text)
        return
    assert text.startpos <= ast_nodes[0].startpos
    assert ast_nodes[-1].startpos < text.endpos
    if text.startpos != ast_nodes[0].startpos:
        # Starting noncode lines.
        # FileText slicing accepts FilePos bounds; mypy models slice indices as int-only.
        yield ([], text[text.startpos:ast_nodes[0].startpos])  # type: ignore[misc]
    end_sentinel = _DummyAst_Node()
    end_sentinel.startpos = text.endpos
    for node, next_node in zip(ast_nodes, ast_nodes[1:] + [end_sentinel]):
        startpos = node.startpos
        next_startpos = next_node.startpos
        assert startpos < next_startpos
        # The statement occupies whole lines from ``startpos`` through its last
        # line.  The parser reports that last line correctly across multiline
        # strings and backslash continuations into *code*; the trailing newline
        # and any inline comment on it belong to the statement.  Standalone
        # comment and blank lines before the next node become a separate
        # noncode chunk.
        if next_startpos.lineno <= node.endpos.lineno:
            # The next node begins on the same physical line, e.g. statements
            # separated by ";".  End exactly where the next one starts.
            endpos = next_startpos
        else:
            end_lineno = node.endpos.lineno
            # A backslash continuation onto a following comment/blank line is
            # part of the statement's source but not its AST extent (e.g.
            # ``b\<newline># c``).  Extend over such continuations.  A trailing
            # ``\`` is only a real continuation when no comment precedes it.
            tail = str(text[end_lineno][node.endpos.colno - 1:])  # type: ignore[index]
            while (tail.endswith("\\") and "#" not in tail
                   and end_lineno < next_startpos.lineno):
                end_lineno += 1
                tail = str(text[end_lineno])
            endpos = min(FilePos(end_lineno + 1, 1), next_startpos)
        assert startpos < endpos <= next_startpos
        # FileText slicing accepts FilePos bounds; mypy models slice indices as int-only.
        yield ([node], text[startpos:endpos])  # type: ignore[misc]
        if endpos != next_startpos:
            yield ([], text[endpos:next_startpos])  # type: ignore[misc]


def infer_compile_mode(arg:ast.AST) -> Literal['exec','eval','single']:
    """
    Infer the mode needed to compile ``arg``.

    :type arg:
      ``ast.AST``
    :rtype:
      ``str``
    """
    # Infer mode from ast object.
    if isinstance(arg, ast.Module):
        return "exec"
    elif isinstance(arg, ast.Expression):
        return "eval"
    elif isinstance(arg, ast.Interactive):
        return "single"
    else:
        raise TypeError(
            "Expected Module/Expression/Interactive ast node; got %s"
            % (type(arg).__name__))


class _DummyAst_Node:
    startpos: FilePos


class PythonStatement:
    r"""
    Representation of a top-level Python statement or consecutive
    comments/blank lines.

      >>> PythonStatement('print("x",\n file=None)\n')  #doctest: +SKIP
      PythonStatement('print("x",\n file=None)\n')

    Implemented as a wrapper around a `PythonBlock` containing at most one
    top-level AST node.
    """

    block: "PythonBlock"

    def __new__(
        cls,
        arg: Union[FileText, str],
        filename: Optional[Filename] = None,
        startpos: Optional[FilePos] = None,
    ) -> "PythonStatement":

        if not isinstance(arg, (FileText, str)):
            raise TypeError("PythonStatement: unexpected %s" % type(arg).__name__)

        block = PythonBlock(arg, filename=filename, startpos=startpos)

        return cls.from_block(block)

    @classmethod
    def from_statement(cls, statement: "PythonStatement") -> "PythonStatement":
        assert isinstance(statement, cls), (statement, cls)
        return statement

    @classmethod
    def from_block(cls, block:PythonBlock) -> PythonStatement:
        """
        Return a statement from a PythonBlock

        This assume the PythonBlock is a single statement and check the comments
        to not start with newlines.
        """
        statements = block.statements
        if len(statements) != 1:
            raise ValueError(
                "Code contains %d statements instead of exactly 1: %r"
                % (len(statements), block)
            )
        (statement,) = statements
        assert isinstance(statement, cls)
        if statement.is_comment:
            assert not statement.text.joined.startswith("\n")
        return statement


    @classmethod
    def _construct_from_block(cls, block:PythonBlock) -> "PythonStatement":
        # Only to be used by PythonBlock.
        assert isinstance(block, PythonBlock), repr(block)
        self = object.__new__(cls)
        self.block = block
        if self.is_comment:
            assert not self.text.joined.startswith("\n"), self.text.joined
        return self

    @property
    def text(self) -> FileText:
        """
        :rtype:
          `FileText`
        """
        return self.block.text

    @property
    def filename(self) -> Optional[Filename]:
        """
        :rtype:
          `Filename`
        """
        return self.text.filename

    @property
    def startpos(self) -> FilePos:
        """
        :rtype:
          `FilePos`
        """
        return self.text.startpos

    @property
    def flags(self) -> CompilerFlags:
        """
        :rtype:
          `CompilerFlags`
        """
        return self.block.flags

    @property
    def ast_node(self) -> Optional[ast.AST]:
        """
        A single AST node representing this statement, or ``None`` if this
        object only represents comments/blanks.

        :rtype:
          ``ast.AST`` or ``NoneType``
        """
        ast_nodes = self.block.ast_node.body
        if len(ast_nodes) == 0:
            return None
        if len(ast_nodes) == 1:
            return ast_nodes[0]
        raise AssertionError("More than one AST node in block")

    @property
    def is_blank(self) -> bool:
        return self.ast_node is None and self.text.joined.strip() == ''

    @property
    def is_comment(self) -> bool:
        return self.ast_node is None and self.text.joined.strip() != ''

    @property
    def is_comment_or_blank(self) -> bool:
        return self.is_comment or self.is_blank

    @property
    def is_comment_or_blank_or_string_literal(self) -> bool:
        return (self.is_comment_or_blank
                or _ast_str_literal_value(self.ast_node) is not None)

    @property
    def is_import(self) -> bool:
        return isinstance(self.ast_node, (ast.Import, ast.ImportFrom))

    @property
    def is_single_assign(self) -> bool:
        n = self.ast_node
        return isinstance(n, ast.Assign) and len(n.targets) == 1

    def get_assignment_literal_value(self) -> Tuple[str, Any]:
        """
        If the statement is an assignment, return the name and literal value.

          >>> PythonStatement('foo = {1: {2: 3}}').get_assignment_literal_value()
          ('foo', {1: {2: 3}})

        :return:
          (target, literal_value)
        """
        if not self.is_single_assign:
            raise ValueError(
                "Statement is not an assignment to a single name: %s" % self)
        n = self.ast_node
        target_name = n.targets[0].id  # type: ignore[union-attr]
        literal_value = ast.literal_eval(n.value)  # type: ignore[union-attr]
        return (target_name, literal_value)

    def __repr__(self) -> str:
        r = repr(self.block)
        assert r.startswith("PythonBlock(")
        r = "PythonStatement(" + r[12:]
        return r

    def __eq__(self, other: Any) -> bool:
        if self is other:
            return True
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return self.block == other.block

    def __ne__(self, other: Any) -> bool:
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return self.block < other.block

    def __cmp__(self, other: Any) -> int:
        if self is other:
            return 0
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return cmp(self.block, other.block)

    def __hash__(self) -> int:
        return hash(self.block)


class AnnotatedAst(ast.AST):
    text: FileText
    flags: CompilerFlags
    source_flags: CompilerFlags
    startpos: FilePos
    endpos: FilePos
    lieneno: int
    col_offset: int
    value: AnnotatedAst
    s: str
    body: Any


class AnnotatedModule(ast.Module, AnnotatedAst):
    source_flags: CompilerFlags


@total_ordering
class PythonBlock:
    r"""
    Representation of a sequence of consecutive top-level
    statements containing at most one AST node.

      >>> source_code = '# 1\nprint(2)\n# 3\n# 4\nprint(5)\nx=[6,\n 7]\n# 8\n'
      >>> codeblock = PythonBlock(source_code)
      >>> for stmt in PythonBlock(codeblock).statements:
      ...     print(stmt)
      PythonStatement('# 1\n')
      PythonStatement('print(2)\n', startpos=(2,1))
      PythonStatement('# 3\n# 4\n', startpos=(3,1))
      PythonStatement('print(5)\n', startpos=(5,1))
      PythonStatement('x=[6,\n 7]\n', startpos=(6,1))
      PythonStatement('# 8\n', startpos=(8,1))

    A ``PythonBlock`` has a ``flags`` attribute that gives the compiler_flags
    associated with the __future__ features using which the code should be
    parsed.

    """

    text: FileText
    _input_flags: Union[int,CompilerFlags]

    def __new__(
        cls,
        arg: Any,
        filename: Any = None,
        startpos: Any = None,
        flags: Any = None,
    ) -> "PythonBlock":
        if isinstance(arg, PythonStatement):
            arg = arg.block
            # Fall through
        if isinstance(arg, cls):
            if filename is startpos is flags is None:
                return arg
            flags = CompilerFlags(flags, arg.flags)
            arg = arg.text
            # Fall through
        if isinstance(arg, (FileText, Filename, str)):
            return cls.from_text(
                arg, filename=filename, startpos=startpos, flags=flags)
        raise TypeError("%r: unexpected %r"
                        % (cls.__name__, type(arg).__name__,))

    @classmethod
    def from_filename(cls, filename: Union[Filename, str]) -> "PythonBlock":
        return cls.from_text(Filename(filename))

    @classmethod
    def from_text(
        cls,
        text: Union[FileText, Filename, str],
        filename: Any = None,
        startpos: Any = None,
        flags: Any = None,
    ) -> "PythonBlock":
        """
        :type text:
          `FileText` or convertible
        :type filename:
          ``Filename``
        :param filename:
          Filename, if not already given by ``text``.
        :type startpos:
          ``FilePos``
        :param startpos:
          Starting position, if not already given by ``text``.
        :type flags:
          ``CompilerFlags``
        :param flags:
          Input compiler flags.
        :rtype:
          `PythonBlock`
        """
        if isinstance(filename, str):
            filename = Filename(filename)
        assert isinstance(filename, (Filename, NoneType)), filename
        self = object.__new__(cls)
        self.text = FileText(text, filename=filename, startpos=startpos)
        self._input_flags = CompilerFlags(flags)
        return self

    @classmethod
    def __construct_from_annotated_ast(
        cls, annotated_ast_nodes: Any, text: FileText, flags: Any
    ) -> "PythonBlock":
        # Constructor for internal use by _split_by_statement() or
        # concatenate().
        ast_node = AnnotatedModule(annotated_ast_nodes, type_ignores=[])
        ast_node.text = text
        ast_node.flags = flags
        if not hasattr(ast_node, "source_flags"):
            ast_node.source_flags = CompilerFlags.from_ast(annotated_ast_nodes)
        self = object.__new__(cls)
        self._ast_node_or_parse_exception = ast_node
        self.ast_node                     = ast_node
        self.annotated_ast_node           = ast_node
        self.text                         = text
        self.flags                        = flags
        self._input_flags                 = flags
        return self

    @classmethod
    def concatenate(
        cls, blocks: Iterable[Any], assume_contiguous: Any = _sentinel
    ) -> "PythonBlock":
        """
        Concatenate a bunch of blocks into one block.

        :type blocks:
          sequence of `PythonBlock` s and/or `PythonStatement` s
        :param assume_contiguous:
          Deprecated, always True
          Whether to assume, without checking, that the input blocks were
          originally all contiguous.  This must be set to True to indicate the
          caller understands the assumption; False is not implemented.
        """
        if assume_contiguous is not _sentinel:
            warnings.warn('`assume_continuous` is deprecated and considered always `True`')
            assume_contiguous = True
        if not assume_contiguous:
            raise NotImplementedError
        blocks2 = []
        for b in blocks:
            if isinstance(b, PythonStatement):
                b = b.block
            if not isinstance(b, PythonBlock):
                b = PythonBlock(b)
            blocks2.append(b)
        blocks = blocks2
        if len(blocks) == 1:
            return blocks[0]
        assert blocks
        text = FileText.concatenate([b.text for b in blocks])
        # The contiguous assumption is important here because ``ast_node``
        # contains line information that would otherwise be wrong.
        ast_nodes = [n for b in blocks for n in b.annotated_ast_node.body]
        flags = blocks[0].flags
        return cls.__construct_from_annotated_ast(ast_nodes, text, flags)

    @property
    def filename(self) -> Optional[Filename]:
        return self.text.filename

    @property
    def startpos(self) -> FilePos:
        return self.text.startpos

    @property
    def endpos(self) -> FilePos:
        return self.text.endpos

    @cached_property
    def _ast_node_or_parse_exception(self) -> Union[AnnotatedModule, Exception]:
        """
        Attempt to parse this block of code into an abstract syntax tree.
        Cached (including exception case).

        :return:
          Either ast_node or exception.
        """
        # This attribute may also be set by __construct_from_annotated_ast(),
        # in which case this code does not run.
        try:
            return _parse_ast_nodes(
                self.text, self._input_flags, "exec")
        except Exception as e:
            # Add the filename to the exception message to be nicer.
            if self.text.filename:
                try:
                    e = type(e)("While parsing %s: %s" % (self.text.filename, e))
                except TypeError:
                    # Exception takes more than one argument
                    pass
            # Cache the exception to avoid re-attempting while debugging.
            return e

    @cached_property
    def parsable(self) -> bool:
        """
        Whether the contents of this ``PythonBlock`` are parsable as Python
        code, using the given flags.

        :rtype:
          ``bool``
        """
        return isinstance(self._ast_node_or_parse_exception, ast.AST)

    @cached_property
    def parsable_as_expression(self) -> bool:
        """
        Whether the contents of this ``PythonBlock`` are parsable as a single
        Python expression, using the given flags.

        :rtype:
          ``bool``
        """
        return self.parsable and self.expression_ast_node is not None

    @cached_property
    def ast_node(self) -> AnnotatedModule:
        """
        Parse this block of code into an abstract syntax tree.

        The returned object type is the kind of AST as returned by the
        ``compile`` built-in (rather than as returned by the older, deprecated
        ``compiler`` module).  The code is parsed using mode="exec".

        The result is a ``ast.Module`` node, even if this block represents only
        a subset of the entire file.

        :rtype:
          ``ast.Module``
        """
        r = self._ast_node_or_parse_exception
        if isinstance(r, ast.AST):
            return r
        else:
            raise r

    @cached_property
    def annotated_ast_node(self) -> AnnotatedAst:
        """
        Return ``self.ast_node``, annotated in place with positions.

        All nodes are annotated with ``startpos``.
        All top-level nodes are annotated with ``endpos``.

        :rtype:
          ``ast.Module``
        """
        result = self.ast_node
        # ! result is mutated and returned
        return _annotate_ast_nodes(result)

    @cached_property
    def expression_ast_node(self) -> Optional[ast.Expression]:
        """
        Return an ``ast.Expression`` if ``self.ast_node`` can be converted into
        one.  I.e., return parse(self.text, mode="eval"), if possible.

        Otherwise, return ``None``.

        :rtype:
          ``ast.Expression``
        """
        node = self.ast_node
        if len(node.body) == 1 and isinstance(node.body[0], ast.Expr):
            return ast.Expression(node.body[0].value)
        else:
            return None

    def parse(self, mode: Optional[str] = None) -> Union[ast.Expression, ast.Module]:
        """
        Parse the source text into an AST.

        :param mode:
          Compilation mode: "exec", "single", or "eval".  "exec", "single",
          and "eval" work as the built-in ``compile`` function do.  If ``None``,
          then default to "eval" if the input is a string with a single
          expression, else "exec".
        :rtype:
          ``ast.AST``
        """
        if mode == "exec":
            assert isinstance(self.ast_node, ast.Module)
            return self.ast_node
        elif mode == "eval":
            if self.expression_ast_node:
                assert isinstance(self.ast_node, ast.Expression)
                return self.expression_ast_node
            else:
                raise SyntaxError
        elif mode is None:
            if self.expression_ast_node:
                return self.expression_ast_node
            else:
                assert isinstance(self.ast_node, ast.Module)
                return self.ast_node
        elif mode == "exec":
            raise NotImplementedError
        else:
            raise ValueError("parse(): invalid mode=%r" % (mode,))

    def compile(self, mode: Optional[str] = None) -> "CodeType":
        """
        Parse into AST and compile AST into code.

        :rtype:
          ``CodeType``
        """
        ast_node = self.parse(mode=mode)
        c_mode = infer_compile_mode(ast_node)
        filename = str(self.filename or "<unknown>")
        return compile(ast_node, filename, c_mode)

    @cached_property
    def statements(self) -> Tuple[PythonStatement, ...]:
        r"""
        Partition of this ``PythonBlock`` into individual ``PythonStatement`` s.
        Each one contains at most 1 top-level ast node.  A ``PythonStatement``
        can contain no ast node to represent comments.

          >>> code = "# multiline\n# comment\n'''multiline\nstring'''\nblah\n"
          >>> print(PythonBlock(code).statements) # doctest:+NORMALIZE_WHITESPACE
          (PythonStatement('# multiline\n# comment\n'),
           PythonStatement("'''multiline\nstring'''\n", startpos=(3,1)),
           PythonStatement('blah\n', startpos=(5,1)))

        :rtype:
          ``tuple`` of `PythonStatement` s
        """
        node = self.annotated_ast_node
        nodes_subtexts = list(_split_code_lines(node.body, self.text))  # type: ignore
        cls = type(self)
        statement_blocks: List[PythonBlock] = [
            cls.__construct_from_annotated_ast(subnodes, subtext, self.flags)
            for subnodes, subtext in nodes_subtexts]

        no_newline_blocks = []
        for block in statement_blocks:
            # The ast parsing make "comments" start at the ends of the previous node,
            # so might including starting with blank lines. We never want blocks to
            # start with new liens or that messes up the formatting code that insert/count new lines.
            while block.text.joined.startswith("\n") and block.text.joined != "\n":
                first, *other = block.text.lines
                assert not first.endswith('\n')
                no_newline_blocks.append(
                    PythonBlock(
                        first+'\n',
                        filename=block.filename,
                        startpos=block.startpos,
                        flags=block.flags,
                    )
                )
                # assert block.startpos == (0,0), (block.startpos, block.text.joined)
                # just use lines 1: here and decrease startpos ?
                block = PythonBlock(
                    "\n".join(other),
                    filename=block.filename,
                    startpos=block.startpos,
                    flags=block.flags,
                )
            no_newline_blocks.append(block)

        # Convert to statements.
        statements = []
        for b in no_newline_blocks:
            assert isinstance(b, PythonBlock)
            statement = PythonStatement._construct_from_block(b)
            statements.append(statement)
        return tuple(statements)

    @cached_property
    def source_flags(self) -> CompilerFlags:
        """
        If the AST contains __future__ imports, then the compiler_flags
        associated with them.  Otherwise, 0.

        The difference between ``source_flags`` and ``flags`` is that ``flags``
        may be set by the caller (e.g. based on an earlier __future__ import)
        and include automatically guessed flags, whereas ``source_flags`` is
        only nonzero if this code itself contains __future__ imports.

        :rtype:
          `CompilerFlags`
        """
        return self.ast_node.source_flags

    @cached_property
    def flags(self) -> CompilerFlags:
        """
        The compiler flags for this code block, including both the input flags
        (possibly automatically guessed), and the flags from "__future__"
        imports in the source code text.

        :rtype:
          `CompilerFlags`
        """
        return self.ast_node.flags

    def groupby(
        self, predicate: Callable[[PythonStatement], Any]
    ) -> Generator[Tuple[Any, "PythonBlock"], None, None]:
        """
        Partition this block of code into smaller blocks of code which
        consecutively have the same ``predicate``.

        :param predicate:
          Function that takes a `PythonStatement` and returns a value.
        :return:
          Generator that yields (group, `PythonBlock` s).
        """
        cls = type(self)
        for pred, stmts in groupby(self.statements, predicate):
            blocks = [s.block for s in stmts]
            yield pred, cls.concatenate(blocks)

    def string_literals(self) -> Iterator[Any]:
        r"""
        Yield all string literals anywhere in this block, in source order.

        The string literals have ``startpos`` attributes attached.

          >>> block = PythonBlock("'a' + ('b' + \n'c')")
          >>> [(f.value, f.startpos) for f in block.string_literals()]
          [('a', FilePos(1,1)), ('b', FilePos(1,8)), ('c', FilePos(2,1))]

        :return:
          Iterable of ``ast.Constant`` (str or bytes) nodes
        """
        nodes = [
            node
            for node in ast.walk(self.annotated_ast_node)
            if _is_ast_str_or_byte(node)
        ]
        nodes.sort(key=lambda node: node.startpos)  # type: ignore[attr-defined]
        yield from nodes

    def _get_docstring_nodes(self) -> Iterator[Any]:
        """
        Yield docstring AST nodes, in source order.

        We consider the following to be docstrings::

          - First literal string of function definitions, class definitions,
            and modules (the python standard)
          - Literal strings after assignments

        :rtype:
          Generator of ``ast.Constant`` (str) nodes
        """
        # This is similar to ``ast.get_docstring``, but:
        #   - This function is recursive
        #   - This function yields the node object, rather than the string
        #   - This function yields multiple docstrings (even per ast node)
        #   - This function doesn't raise TypeError on other AST types
        #   - This function doesn't cleandoc
        docstring_containers = (ast.FunctionDef, ast.ClassDef, ast.Module, AsyncFunctionDef)
        found = []
        for node in ast.walk(self.annotated_ast_node):
            if not isinstance(node, docstring_containers):
                continue
            if not node.body:
                continue
            # If the first body item is a literal string, then yield the node.
            if (isinstance(node.body[0], ast.Expr) and
                _is_ast_str(node.body[0].value)):
                found.append(node.body[0].value)
            for i in range(1, len(node.body)-1):
                # If a body item is an assignment and the next one is a
                # literal string, then yield the node for the literal string.
                n1, n2 = node.body[i], node.body[i+1]
                if (isinstance(n1, ast.Assign) and
                    isinstance(n2, ast.Expr) and
                    _is_ast_str(n2.value)):
                    found.append(n2.value)
        found.sort(key=lambda node: node.startpos)  # type: ignore[attr-defined]
        yield from found

    def get_doctests(self) -> List["PythonBlock"]:
        r"""
        Return doctests in this code.

          >>> PythonBlock("x\n'''\n >>> foo(bar\n ...     + baz)\n'''\n").get_doctests()
          [PythonBlock('foo(bar\n    + baz)\n', startpos=(3,2))]

        :rtype:
          ``list`` of `PythonStatement` s
        """
        parser = IgnoreOptionsDocTestParser()
        doctest_blocks = []
        filename = self.filename
        flags = self.flags
        for ast_node in self._get_docstring_nodes():
            try:
                examples = parser.get_examples(ast_node.value)
            except Exception:
                blob = ast_node.s
                if len(blob) > 60:
                    blob = blob[:60] + '...'
                # TODO: let caller decide how to handle
                logger.warning("Can't parse docstring; ignoring: %r", blob)
                continue
            for example in examples:
                lineno = ast_node.startpos.lineno + example.lineno
                colno = ast_node.startpos.colno + example.indent # dubious
                text = FileText(example.source, filename=filename,
                                startpos=(lineno,colno))
                try:
                    block = PythonBlock(text, flags=flags)
                    block.ast_node # make sure we can parse
                except Exception:
                    blob = text.joined
                    if len(blob) > 60:
                        blob = blob[:60] + '...'
                    logger.warning("Can't parse doctest; ignoring: %r", blob)
                    continue
                doctest_blocks.append(block)
        return doctest_blocks

    def __repr__(self) -> str:
        r = "%s(%r" % (type(self).__name__, self.text.joined)
        if self.filename:
            r += ", filename=%r" % (str(self.filename),)
        if self.startpos != FilePos():
            r += ", startpos=%s" % (self.startpos,)
        if self.flags != self.source_flags:
            r += ", flags=%s" % (self.flags,)
        r += ")"
        return r

    def __str__(self) -> str:
        return str(self.text)

    def __eq__(self, other: Any) -> bool:
        if self is other:
            return True
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return self.text == other.text and self.flags == other.flags

    def __ne__(self, other: Any) -> bool:
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return (self.text, self.flags) < (other.text, other.flags)

    def __cmp__(self, other: Any) -> int:
        if self is other:
            return 0
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return cmp(self.text, other.text) or cmp(self.flags, other.flags)

    def __hash__(self) -> int:
        h = hash((self.text, self.flags))
        self.__hash__ = lambda: h  # type: ignore[method-assign]
        return h

class IgnoreOptionsDocTestParser(DocTestParser):
    def _find_options(
        self, source: str, name: str, lineno: int
    ) -> Dict[Any, Any]:
        # Ignore doctest options. We don't use them, and we don't want to
        # error on unknown options, which is what the default DocTestParser
        # does.
        return {}
