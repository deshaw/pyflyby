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

from   collections              import namedtuple
from   doctest                  import DocTestParser
from   functools                import cached_property, total_ordering
from   itertools                import groupby

from   pyflyby._file            import FilePos, FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._log             import logger
from   pyflyby._util            import cmp

from   ast                      import MatchAs, MatchMapping
import re
import sys
from   textwrap                 import dedent
import types
from   types                    import NoneType
from   typing                   import (Any, List, Literal, Optional, Tuple,
                                        Union, cast)
import warnings


_sentinel = object()

if sys.version_info >= (3, 14):
    from ast import TemplateStr
else:
    TemplateStr = None  # type: ignore


def _is_comment_or_blank(line, /):
    """
    Returns whether a line of python code contains only a comment is blank.

      >>> _is_comment_or_blank("foo\\n")
      False

      >>> _is_comment_or_blank("  # blah\\n")
      True
    """
    return re.sub("#.*", "", line).rstrip() == ""


def _is_ast_str_or_byte(node) -> bool:
    """
    utility function that test if node is an ast.Str|ast.Bytes in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    return _is_ast_str(node) or _is_ast_bytes(node)

def _is_ast_bytes(node) -> bool:
    """
    utility function that test if node is an ast.Str in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    if sys.version_info < (3,12):
        return isinstance(node, ast.Bytes)
    else:
        return (isinstance(node, ast.Constant) and isinstance(node.value , bytes))


def _is_ast_str(node) -> bool:
    """
    utility function that test if node is an ast.Str in Python < 3.12,
    and if it is a ast.Constant, with node.value being a str in newer version.
    """
    if sys.version_info < (3,12):
        return isinstance(node, ast.Str)
    else:
        return (isinstance(node, ast.Constant) and isinstance(node.value , str))

def _ast_str_literal_value(node):
    if _is_ast_str_or_byte(node):
        return node.s
    if isinstance(node, ast.Expr) and _is_ast_str_or_byte(node.value):
        return node.value.value
    else:
        return None


def _flatten_ast_nodes(arg):
    if arg is None:
        pass
    elif isinstance(arg, ast.AST):
        yield arg
    elif isinstance(arg, str):
        #FunctionDef type_comments
        yield arg
    elif isinstance(arg, (tuple, list, types.GeneratorType)):
        for x in arg:
            for y in _flatten_ast_nodes(x):
                yield y
    else:
        raise TypeError(
            "_flatten_ast_nodes: unexpected %s" % (type(arg).__name__,))


def _iter_child_nodes_in_order(node):
    """
    Yield all direct child nodes of ``node``, that is, all fields that are nodes
    and all items of fields that are lists of nodes.

    ``_iter_child_nodes_in_order`` yields nodes in the same order that they
    appear in the source.

    ``ast.iter_child_nodes`` does the same thing, but not in source order.
    e.g. for ``Dict`` s, it yields all key nodes before all value nodes.

    `JoinedStr` for `f"{x=}"` also does not.
    """
    return _flatten_ast_nodes(_iter_child_nodes_in_order_internal_1(node))


def _iter_child_nodes_in_order_internal_1(node):
    if isinstance(node, str):
        # this happen for type comments which are not ast nodes but str
        # they do not have children. We yield nothing.
        yield []
        return
    if not isinstance(node, ast.AST):
        raise TypeError
    if isinstance(node, ast.Dict):
        assert node._fields == ("keys", "values")
        yield list(zip(node.keys, node.values))
    elif isinstance(node, (ast.FunctionDef, AsyncFunctionDef)):
        if sys.version_info < (3,12):
            assert node._fields == (
                "name",
                "args",
                "body",
                "decorator_list",
                "returns",
                "type_comment",
            ), node._fields
            res = (
                node.type_comment,
                node.decorator_list,
                node.args,
                node.returns,
                node.body,
            )
            yield res
        else:
            assert node._fields == (
                "name",
                "args",
                "body",
                "decorator_list",
                "returns",
                "type_comment",
                "type_params"
            ), node._fields
            res = (
                node.type_comment,
                node.decorator_list,
                node.type_params,
                node.args,
                node.returns,
                node.body,
            )
            yield res


        # node.name is a string, not an AST node
    elif isinstance(node, ast.arguments):
        assert node._fields == ('posonlyargs', 'args', 'vararg', 'kwonlyargs',
                                'kw_defaults', 'kwarg', 'defaults'), node._fields
        args = node.posonlyargs + node.args
        defaults = node.defaults or ()
        num_no_default = len(args) - len(defaults)
        yield args[:num_no_default]
        yield list(zip(args[num_no_default:], defaults))
        # node.varags and node.kwarg are strings, not AST nodes.
    elif isinstance(node, ast.IfExp):
        assert node._fields == ('test', 'body', 'orelse')
        yield node.body, node.test, node.orelse
    elif isinstance(node, ast.Call):
        # call arguments order are lost by ast, re-order them
        yield node.func
        args = sorted([(k.value.lineno, k.value.col_offset, k) for k in node.keywords]+
                      [(k.lineno,k.col_offset, k) for k in node.args])
        yield [a[2] for a in args]
    elif isinstance(node, ast.ClassDef):
        if sys.version_info > (3, 12):
            assert node._fields == ('name', 'bases', 'keywords', 'body', 'decorator_list', 'type_params'), node._fields
            yield node.decorator_list, node.type_params, node.bases, node.body
        else:
            assert node._fields == ('name', 'bases', 'keywords', 'body', 'decorator_list'), node._fields
            yield node.decorator_list, node.bases, node.body
        # node.name is a string, not an AST node
    elif isinstance(node, ast.FormattedValue):
        assert node._fields == ('value', 'conversion', 'format_spec')
        yield node.value,
    elif isinstance(node, ast.JoinedStr) or (
        TemplateStr is not None and isinstance(node, TemplateStr)
    ):
        assert node._fields == ("values",)
        # Sort values by their position in the source code
        # for f"{x=}" / t"{x=}", nodes are not in order
        sorted_children = sorted(node.values, key=lambda v: (v.lineno, v.col_offset))
        yield sorted_children
    elif isinstance(node, MatchAs):
        yield node.pattern
        yield node.name,
    elif isinstance(node, MatchMapping):
        for k, p in zip(node.keys, node.patterns):
            pass
            yield k, p
    else:
        # Default behavior.
        yield ast.iter_child_nodes(node)


def _walk_ast_nodes_in_order(node):
    """
    Recursively yield all child nodes of ``node``, in the same order that the
    node appears in the source.

    ``ast.walk`` does the same thing, but yields nodes in an arbitrary order.
    """
    # The implementation is basically the same as ``ast.walk``, but:
    #   1. Use a stack instead of a deque.  (I.e., depth-first search instead
    #      of breadth-first search.)
    #   2. Use _iter_child_nodes_in_order instead of ``ast.iter_child_nodes``.
    todo = [node]
    while todo:
        node = todo.pop()
        yield node
        todo.extend(reversed(list(_iter_child_nodes_in_order(node))))


def _flags_to_try(source:str, flags, auto_flags, mode):
    """
    Flags to try for ``auto_flags``.

    If ``auto_flags`` is False, then only yield ``flags``.
    If ``auto_flags`` is True, then yield ``flags`` and ``flags ^ print_function``.
    """
    flags = CompilerFlags(flags)
    if re.search(r"# *type:", source):
        flags = flags | CompilerFlags('type_comments')
    yield flags
    return


def _parse_ast_nodes(text:FileText, flags:CompilerFlags, auto_flags:bool, mode:str):
    """
    Parse a block of lines into an AST.

    Also annotate ``input_flags``, ``source_flags``, and ``flags`` on the
    resulting ast node.

    :type text:
      ``FileText``
    :type flags:
      ``CompilerFlags``
    :type auto_flags:
      ``bool``
    :param auto_flags:
      Whether to guess different flags if ``text`` can't be parsed with
      ``flags``.
    :param mode:
      Compilation mode: "exec", "single", or "eval".
    :rtype:
      ``ast.Module``
    """
    assert isinstance(text, FileText)
    filename = str(text.filename) if text.filename else "<unknown>"
    source = text.joined
    source = dedent(source)
    if not source.endswith("\n"):
        # Ensure that the last line ends with a newline (``ast`` barfs
        # otherwise).
        source += "\n"
    exp = None
    for flags in _flags_to_try(source, flags, auto_flags, mode):
        cflags = ast.PyCF_ONLY_AST | int(flags)
        try:
            result = compile(
                source, filename, mode, flags=cflags, dont_inherit=True)
        except SyntaxError as e:
            exp = e
            pass
        else:
            # Attach flags to the result.
            result.input_flags = flags
            result.source_flags = CompilerFlags.from_ast(result)
            result.flags = result.input_flags | result.source_flags
            result.text = text
            return result
    # None, would be unraisable and Mypy would complains below
    assert exp is not None
    raise exp



def _test_parse_string_literal(text:str, flags:CompilerFlags):
    r"""
    Attempt to parse ``text``.  If it parses cleanly to a single string
    literal, return its value.  Otherwise return ``None``.

      >>> _test_parse_string_literal(r'"foo\n" r"\nbar"', None)
      'foo\n\\nbar'

    """
    filetext = FileText(text)
    try:
        module_node = _parse_ast_nodes(filetext, flags, False, "eval")
    except SyntaxError:
        return None
    body = module_node.body
    if not _is_ast_str_or_byte(body):
        return None
    return body.value


AstNodeContext = namedtuple("AstNodeContext", "parent field index")


def _annotate_ast_nodes(ast_node: ast.AST) -> AnnotatedAst:
    """
    Annotate AST with:
      - startpos and endpos
      - [disabled for now: context as `AstNodeContext` ]

    :type ast_node:
      ``ast.AST``
    :param ast_node:
      AST node returned by `_parse_ast_nodes`
    :return:
      ``None``
    """
    aast_node: AnnotatedAst = ast_node  # type: ignore
    text = aast_node.text
    flags = aast_node.flags
    startpos = text.startpos
    _annotate_ast_startpos(aast_node, None, startpos, text, flags)
    return aast_node


def _annotate_ast_startpos(
    ast_node: ast.AST, parent_ast_node, minpos: FilePos, text: FileText, flags
) -> bool:
    r"""
    Annotate ``ast_node``.  Set ``ast_node.startpos`` to the starting position
    of the node within ``text``.

    For "typical" nodes, i.e. those other than multiline strings, this is
    simply FilePos(ast_node.lineno, ast_node.col_offset+1), but taking
    ``text.startpos`` into account.

    For multiline string nodes, this function works by trying to parse all
    possible subranges of lines until finding the range that is syntactically
    valid and matches ``value``.  The candidate range is
    text[min_start_lineno:lineno+text.startpos.lineno+1].

    This function is unfortunately necessary because of a flaw in the output
    produced by the Python built-in parser.  For some crazy reason, the
    ``ast_node.lineno`` attribute represents something different for multiline
    string literals versus all other statements.  For multiline string literal
    nodes and statements that are just a string expression (or more generally,
    nodes where the first descendant leaf node is a multiline string literal),
    the compiler attaches the ending line number as the value of the ``lineno``
    attribute.  For all other than AST nodes, the compiler attaches the
    starting line number as the value of the ``lineno`` attribute.  This means
    e.g. the statement "'''foo\nbar'''" has a lineno value of 2, but the
    statement "x='''foo\nbar'''" has a lineno value of 1.

    :type ast_node:
      ``ast.AST``
    :type minpos:
      ``FilePos``
    :param minpos:
      Earliest position to check, in the number space of ``text``.
    :type text:
      ``FileText``
    :param text:
      Source text that was used to parse the AST, whose ``startpos`` should be
      used in interpreting ``ast_node.lineno`` (which always starts at 1 for
      the subset that was parsed).
    :type flags:
      ``CompilerFlags``
    :param flags:
      Compiler flags to use when re-compiling code.
    :return:
      ``True`` if this node is a multiline string literal or the first child is
      such a node (recursively); ``False`` otherwise.
    :raise ValueError:
      Could not find the starting line number.
    """
    assert isinstance(ast_node, (ast.AST, str, TypeIgnore)), ast_node
    aast_node: AnnotatedAst = cast(AnnotatedAst, ast_node)

    # First, traverse child nodes.  If the first child node (recursively) is a
    # multiline string, then we need to transfer its information to this node.
    # Walk all nodes/fields of the AST.  We implement this as a custom
    # depth-first search instead of using ast.walk() or ast.NodeVisitor
    # so that we can easily keep track of the preceding node's lineno.
    child_minpos: FilePos = minpos
    is_first_child: bool = True
    leftstr_node = None
    for child_node in _iter_child_nodes_in_order(aast_node):
        leftstr = _annotate_ast_startpos(
            child_node, aast_node, child_minpos, text, flags
        )
        if is_first_child and leftstr:
            leftstr_node = child_node
        if hasattr(child_node, 'lineno') and not isinstance(child_node, TypeIgnore):
            if child_node.startpos < child_minpos:
                raise AssertionError(
                    "Got out-of-order AST node(s):\n"
                    "  parent minpos=%s\n" % minpos
                    + "    node: %s\n" % ast.dump(aast_node)
                    + "      fields: %s\n" % (" ".join(aast_node._fields))
                    + "      children:\n"
                    + "".join(
                        "        %s %9s: %s\n"
                        % (
                            ("==>" if cn is child_node else "   "),
                            getattr(cn, "startpos", ""),
                            ast.dump(cn),
                        )
                        for cn in _iter_child_nodes_in_order(aast_node)
                    )
                    + "\n"
                    "This indicates a bug in pyflyby._parse\n"
                    "\n"
                    "pyflyby developer: Check if there's a bug or missing ast node handler in "
                    "pyflyby._parse._iter_child_nodes_in_order() - "
                    +"probably the handler for ast.%s." % type(aast_node).__name__
                    +"\n"
                    "Please also run python -m pyflyby.check_parse on the cpython source tree"
                    "to test for new syntax."
                )
            child_minpos = child_node.startpos
        is_first_child = False

    # If the node has no lineno at all, then skip it.  This should only happen
    # for nodes we don't care about, e.g. ``ast.Module`` or ``ast.alias``.
    if not hasattr(aast_node, "lineno") or isinstance(aast_node, TypeIgnore):
        return False
    # If col_offset is set then the lineno should be correct also.
    if aast_node.col_offset >= 0:
        # In Python 3.8+, FunctionDef.lineno is the line with the def. To
        # account for decorators, we need the lineno of the first decorator
        if (
            isinstance(aast_node, (ast.FunctionDef, ast.ClassDef, AsyncFunctionDef))
            and aast_node.decorator_list
        ):
            delta = (
                aast_node.decorator_list[0].lineno - 1,
                # The col_offset doesn't include the @
                aast_node.decorator_list[0].col_offset - 1,
            )
        else:
            delta = (aast_node.lineno - 1, aast_node.col_offset)

        # Not a multiline string literal.  (I.e., it could be a non-string or
        # a single-line string.)
        # Easy.
        if sys.version_info < (3, 12):
            """There is an issue for f-strings at the begining of a file in 3.11 and
            before

            https://github.com/deshaw/pyflyby/issues/361,
            here we ensure a child node min pos, can't be before it's parent.
            """
            startpos = max(text.startpos + delta, minpos)
        else:
            startpos = text.startpos + delta

        # Special case for 'with' statements.  Consider the code:
        #    with X: pass
        #    ^0   ^5
        # Since 'Y's col_offset isn't the beginning of the line, the authors
        # of Python presumably changed 'X's col_offset to also not be the
        # beginning of the line.  If they had made the With ast node support
        # multiple clauses, they wouldn't have needed to do that, but then
        # that would introduce an API change in the AST.  So it's
        # understandable that they did that.
        # Since we use startpos for breaking lines, we need to set startpos to
        # the beginning of the line.
        # In Python 3, the col_offset for the with is 0 again.
        aast_node.startpos = startpos
        return False

    assert aast_node.col_offset == -1
    if leftstr_node:
        # This is an ast node where the leftmost deepest leaf is a
        # multiline string.  The bug that multiline strings have broken
        # lineno/col_offset infects ancestors up the tree.
        #
        # If the leftmost leaf is a multi-line string, then ``lineno``
        # contains the ending line number, and col_offset is -1:
        #   >>> ast.parse("""'''foo\nbar'''+blah""").body[0].lineno
        #   2
        # But if the leftmost leaf is not a multi-line string, then
        # ``lineno`` contains the starting line number:
        #   >>> ast.parse("""'''foobar'''+blah""").body[0].lineno
        #   1
        #   >>> ast.parse("""blah+'''foo\nbar'''+blah""").body[0].lineno
        #   1
        #
        # To fix that, we copy start_lineno and start_colno from the Str
        # node once we've corrected the values.
        assert not _is_ast_str_or_byte(aast_node)
        assert leftstr_node.lineno == aast_node.lineno
        assert leftstr_node.col_offset == -1
        aast_node.startpos = leftstr_node.startpos
        return True

    # a large chunk of what look like unreachable code has been removed from here
    # as the type annotation say many things were impossible (slices indexed by FilePos
    # instead of integers.
    raise ValueError("Couldn't find exact position of %s" % (ast.dump(ast_node)))


def _split_code_lines(ast_nodes, text):
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
        yield ([], text[text.startpos:ast_nodes[0].startpos])
    end_sentinel = _DummyAst_Node()
    end_sentinel.startpos = text.endpos
    for node, next_node in zip(ast_nodes, ast_nodes[1:] + [end_sentinel]):
        startpos = node.startpos
        next_startpos = next_node.startpos
        assert startpos < next_startpos
        # We have the start position of this node.  Figure out the end
        # position, excluding noncode lines (standalone comments and blank
        # lines).
        if hasattr(node, 'endpos'):
            # We have an endpos for the node because this was a multi-line
            # string.  Start with the node endpos.
            endpos = node.endpos
            assert startpos < endpos <= next_startpos
            # enpos points to the character *after* the ending quote, so we
            # know that this is never at the beginning of the line.
            assert endpos.colno != 1
            # Advance past whitespace an inline comment, if any.  Do NOT
            # advance past other code that could be on the same line, nor past
            # blank lines and comments on subsequent lines.
            line = text[endpos : min(text.endpos, FilePos(endpos.lineno+1,1))]
            if _is_comment_or_blank(line):
                endpos = FilePos(endpos.lineno+1, 1)
        else:
            endpos = next_startpos
            assert endpos <= text.endpos
            # We don't have an endpos yet; what we do have is the next node's
            # startpos (or the position at the end of the text).  Start there
            # and work backward.
            if endpos.colno != 1:
                if endpos == text.endpos:
                    # There could be a comment on the last line and no
                    # trailing newline.
                    # TODO: do this in a more principled way.
                    if _is_comment_or_blank(text[endpos.lineno]):
                        assert startpos.lineno < endpos.lineno
                        if not text[endpos.lineno-1].endswith("\\"):
                            endpos = FilePos(endpos.lineno,1)
                else:
                    # We're not at end of file, yet the next node starts in
                    # the middle of the line.  This should only happen with if
                    # we're not looking at a comment.  [The first character in
                    # the line could still be "#" if we're inside a multiline
                    # string that's the last child of the parent node.
                    # Therefore we don't assert 'not
                    # _is_comment_or_blank(...)'.]
                    pass
            if endpos.colno == 1:
                while (endpos.lineno-1 > startpos.lineno and
                       _is_comment_or_blank(text[endpos.lineno-1]) and
                       (not text[endpos.lineno-2].endswith("\\") or
                        _is_comment_or_blank(text[endpos.lineno-2]))):
                    endpos = FilePos(endpos.lineno-1, 1)
        assert startpos < endpos <= next_startpos
        yield ([node], text[startpos:endpos])
        if endpos != next_startpos:
            yield ([], text[endpos:next_startpos])


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
    pass


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

    def __new__(cls, arg:Union[FileText, str], filename=None, startpos=None):

        if not isinstance(arg, (FileText, str)):
            raise TypeError("PythonStatement: unexpected %s" % type(arg).__name__)

        block = PythonBlock(arg, filename=filename, startpos=startpos)

        return cls.from_block(block)

    @classmethod
    def from_statement(cls, statement):
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
    def _construct_from_block(cls, block:PythonBlock):
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
    def startpos(self):
        """
        :rtype:
          `FilePos`
        """
        return self.text.startpos

    @property
    def flags(self):
        """
        :rtype:
          `CompilerFlags`
        """
        return self.block.flags

    @property
    def ast_node(self):
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
    def is_blank(self):
        return self.ast_node is None and self.text.joined.strip() == ''

    @property
    def is_comment(self):
        return self.ast_node is None and self.text.joined.strip() != ''

    @property
    def is_comment_or_blank(self):
        return self.is_comment or self.is_blank

    @property
    def is_comment_or_blank_or_string_literal(self):
        return (self.is_comment_or_blank
                or _ast_str_literal_value(self.ast_node) is not None)

    @property
    def is_import(self):
        return isinstance(self.ast_node, (ast.Import, ast.ImportFrom))

    @property
    def is_single_assign(self):
        n = self.ast_node
        return isinstance(n, ast.Assign) and len(n.targets) == 1

    def get_assignment_literal_value(self):
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
        target_name = n.targets[0].id
        literal_value = ast.literal_eval(n.value)
        return (target_name, literal_value)

    def __repr__(self):
        r = repr(self.block)
        assert r.startswith("PythonBlock(")
        r = "PythonStatement(" + r[12:]
        return r

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return self.block == other.block

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return self.block < other.block

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, PythonStatement):
            return NotImplemented
        return cmp(self.block, other.block)

    def __hash__(self):
        return hash(self.block)


class AnnotatedAst(ast.AST):
    text: FileText
    flags: str
    source_flags: CompilerFlags
    startpos: FilePos
    endpos: FilePos
    lieneno: int
    col_offset: int
    value: AnnotatedAst
    s: str


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
    _auto_flags: bool
    _input_flags: Union[int,CompilerFlags]

    def __new__(cls, arg:Any, filename=None, startpos=None, flags=None,
                auto_flags=None):
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
                arg, filename=filename, startpos=startpos,
                flags=flags, auto_flags=auto_flags)
        raise TypeError("%r: unexpected %r"
                        % (cls.__name__, type(arg).__name__,))

    @classmethod
    def from_filename(cls, filename):
        return cls.from_text(Filename(filename))

    @classmethod
    def from_text(
        cls, text, filename=None, startpos=None, flags=None, auto_flags: bool = False
    ):
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
        :param auto_flags:
          Whether to try other flags if ``flags`` fails.
        :rtype:
          `PythonBlock`
        """
        if isinstance(filename, str):
            filename = Filename(filename)
        assert isinstance(filename, (Filename, NoneType)), filename
        self = object.__new__(cls)
        self.text = FileText(text, filename=filename, startpos=startpos)
        self._input_flags = CompilerFlags(flags)
        self._auto_flags = auto_flags
        return self

    @classmethod
    def __construct_from_annotated_ast(cls, annotated_ast_nodes, text:FileText, flags):
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
        self._auto_flags                  = False
        return self

    @classmethod
    def concatenate(cls, blocks, assume_contiguous=_sentinel):
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
    def filename(self):
        return self.text.filename

    @property
    def startpos(self):
        return self.text.startpos

    @property
    def endpos(self):
        return self.text.endpos

    @cached_property
    def _ast_node_or_parse_exception(self):
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
                self.text, self._input_flags, self._auto_flags, "exec")
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
    def parsable(self):
        """
        Whether the contents of this ``PythonBlock`` are parsable as Python
        code, using the given flags.

        :rtype:
          ``bool``
        """
        return isinstance(self._ast_node_or_parse_exception, ast.AST)

    @cached_property
    def parsable_as_expression(self):
        """
        Whether the contents of this ``PythonBlock`` are parsable as a single
        Python expression, using the given flags.

        :rtype:
          ``bool``
        """
        return self.parsable and self.expression_ast_node is not None

    @cached_property
    def ast_node(self):
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

    def compile(self, mode: Optional[str] = None):
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
    def source_flags(self):
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
    def flags(self):
        """
        The compiler flags for this code block, including both the input flags
        (possibly automatically guessed), and the flags from "__future__"
        imports in the source code text.

        :rtype:
          `CompilerFlags`
        """
        return self.ast_node.flags

    def groupby(self, predicate):
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

    def string_literals(self):
        r"""
        Yield all string literals anywhere in this block.

        The string literals have ``startpos`` attributes attached.

          >>> block = PythonBlock("'a' + ('b' + \n'c')")
          >>> [(f.s, f.startpos) for f in block.string_literals()]
          [('a', FilePos(1,1)), ('b', FilePos(1,8)), ('c', FilePos(2,1))]

        :return:
          Iterable of ``ast.Str``  or ``ast.Bytes`` nodes
        """
        for node in _walk_ast_nodes_in_order(self.annotated_ast_node):
            if _is_ast_str_or_byte(node):
                assert hasattr(node, 'startpos')
                yield node

    def _get_docstring_nodes(self):
        """
        Yield docstring AST nodes.

        We consider the following to be docstrings::

          - First literal string of function definitions, class definitions,
            and modules (the python standard)
          - Literal strings after assignments

        :rtype:
          Generator of ``ast.Str`` nodes
        """
        # This is similar to ``ast.get_docstring``, but:
        #   - This function is recursive
        #   - This function yields the node object, rather than the string
        #   - This function yields multiple docstrings (even per ast node)
        #   - This function doesn't raise TypeError on other AST types
        #   - This function doesn't cleandoc
        docstring_containers = (ast.FunctionDef, ast.ClassDef, ast.Module, AsyncFunctionDef)
        for node in _walk_ast_nodes_in_order(self.annotated_ast_node):
            if not isinstance(node, docstring_containers):
                continue
            if not node.body:
                continue
            # If the first body item is a literal string, then yield the node.
            if (isinstance(node.body[0], ast.Expr) and
                _is_ast_str(node.body[0].value)):
                yield node.body[0].value
            for i in range(1, len(node.body)-1):
                # If a body item is an assignment and the next one is a
                # literal string, then yield the node for the literal string.
                n1, n2 = node.body[i], node.body[i+1]
                if (isinstance(n1, ast.Assign) and
                    isinstance(n2, ast.Expr) and
                    _is_ast_str(n2.value)):
                    yield n2.value

    def get_doctests(self):
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

    def __repr__(self):
        r = "%s(%r" % (type(self).__name__, self.text.joined)
        if self.filename:
            r += ", filename=%r" % (str(self.filename),)
        if self.startpos != FilePos():
            r += ", startpos=%s" % (self.startpos,)
        if self.flags != self.source_flags:
            r += ", flags=%s" % (self.flags,)
        r += ")"
        return r

    def __str__(self):
        return str(self.text)

    def __text__(self):
        return self.text

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return self.text == other.text and self.flags == other.flags

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return (self.text, self.flags) < (other.text, other.flags)

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, PythonBlock):
            return NotImplemented
        return cmp(self.text, other.text) or cmp(self.flags, other.flags)

    def __hash__(self):
        h = hash((self.text, self.flags))
        self.__hash__ = lambda: h
        return h

class IgnoreOptionsDocTestParser(DocTestParser):
    def _find_options(self, source, name, lineno):
        # Ignore doctest options. We don't use them, and we don't want to
        # error on unknown options, which is what the default DocTestParser
        # does.
        return {}
