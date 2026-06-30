# pyflyby/_imports2s.py.
# Copyright (C) 2011-2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import annotations, print_function

import ast
from   collections              import defaultdict
from   contextlib               import nullcontext
from   pyflyby._autoimp         import scan_for_import_issues
from   pyflyby._file            import FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._importclns      import ImportMap, ImportSet, NoSuchImportError
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import (Import, ImportFormatParams,
                                        ImportStatement,
                                        NonImportStatementError)
from   pyflyby._log             import logger
from   pyflyby._parse           import PythonBlock, PythonStatement
from   pyflyby._util            import (ImportPathCtx, Inf, _has_ignore_pragma,
                                        memoize)
import re
import sys

from   typing                   import (Any, ContextManager, Dict, List,
                                        Literal, Optional, Union)

from   textwrap                 import dedent, indent

# A mapping of dotted-name prefixes to replacements.  ``transform_imports`` and
# friends accept either a plain ``dict`` or an `ImportMap` (e.g. a database's
# ``canonical_imports``); both expose ``.items()``/``.keys()``.
_Transformations = Union[Dict[str, str], ImportMap]

# AST node types for function and class definitions
_FUNCTION_OR_CLASS_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# AST node types for import statements
_IMPORT_TYPES = (ast.Import, ast.ImportFrom)


def _group_consecutive_imports(
    body: list[ast.stmt],
) -> list[list[Union[ast.Import, ast.ImportFrom]]]:
    """Group consecutive import statements from an AST body.

    Parameters
    ----------
    body : list
        List of AST nodes from a function/class body

    Returns
    -------
    list[list]
        List of groups, where each group is a list of consecutive import statements
    """
    import_groups = []
    current_group = []

    for body_item in body:
        if isinstance(body_item, _IMPORT_TYPES):
            current_group.append(body_item)
        else:
            if current_group:
                import_groups.append(current_group)
                current_group = []

    if current_group:
        import_groups.append(current_group)

    return import_groups


class SourceToSourceTransformationBase:

    input: PythonBlock

    def __new__(cls, arg: Any) -> "SourceToSourceTransformationBase":
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonBlock, FileText, Filename, str)):
            return cls._from_source_code(arg)
        raise TypeError("%s: got unexpected %s"
                        % (cls.__name__, type(arg).__name__))

    @classmethod
    def _from_source_code(
        cls, codeblock: Any
    ) -> "SourceToSourceTransformationBase":
        # TODO: don't do that.
        self = object.__new__(cls)
        if isinstance(codeblock, PythonBlock):
            self.input = codeblock
        elif isinstance(codeblock, FileText):
            self.input = PythonBlock(codeblock)
        else:
            if not codeblock.endswith('\n'):
                codeblock += '\n'
            self.input = PythonBlock(codeblock)
        self.preprocess()
        return self

    def preprocess(self) -> None:
        pass

    def pretty_print(self, params: Any = None) -> Union[FileText, str]:
        raise NotImplementedError

    def output(self, params: Any = None) -> PythonBlock:
        """
        Pretty-print and return as a `PythonBlock`.

        :rtype:
          `PythonBlock`
        """
        result: Union[FileText, str, PythonBlock] = self.pretty_print(params=params)
        result = PythonBlock(result, filename=self.input.filename)
        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}\n{indent(str(self.pretty_print()),'    ')}\n at 0x{hex(id(self))}>"


class SourceToSourceTransformation(SourceToSourceTransformationBase):

    _output: PythonBlock

    def preprocess(self) -> None:
        assert isinstance(self.input, PythonBlock), self.input
        self._output = self.input

    def pretty_print(self, params: Any = None) -> FileText:
        return self._output.text


class SourceToSourceImportBlockTransformation(SourceToSourceTransformationBase):

    importset: ImportSet

    def preprocess(self) -> None:
        self.importset = ImportSet(self.input, ignore_shadowed=True)

    def pretty_print(self, params: Any = None) -> str:
        params = ImportFormatParams(params)
        return self.importset.pretty_print(params)

    def __repr__(self) -> str:
        # Guard against partially initialized object...
        import_set = getattr(self, "importset", None)
        return f"<SourceToSourceImportBlockTransformation {import_set!r} @{hex(id(self))}>"


class LineNumberNotFoundError(Exception):
    pass

class LineNumberAmbiguousError(Exception):
    pass


class _LocalImportBlockWrapper:
    """
    Wrapper for import blocks found within function/class bodies.
    Preserves the original line number range since the block's internal line numbers
    may not match the file's line numbers.

    This will be useful for tidy imports which only know how to handle top
    level import.
    """

    transform: SourceToSourceImportBlockTransformation
    # ``importset`` is reachable both via ``__getattr__`` delegation to
    # ``transform`` and by direct assignment (see
    # ``SourceToSourceFileImportsTransformation.remove_import``); declare it so
    # that those reads/writes type-check against the import-block union.
    importset: ImportSet
    start_lineno: int
    end_lineno: int
    _original_imports: set[Import]
    _id: str
    _semicolon_suffixes: dict[int, str]

    def __init__(
        self,
        transform: SourceToSourceImportBlockTransformation,
        start_lineno: int,
        end_lineno: Optional[int] = None,
        semicolon_suffixes: Optional[dict[int, str]] = None,
    ) -> None:
        self.transform = transform
        self.start_lineno = start_lineno
        self.end_lineno = end_lineno if end_lineno is not None else start_lineno
        # Store the original imports so we can detect what was removed
        self._original_imports = set(transform.importset.imports)
        self._id = hex(id(self))
        self._semicolon_suffixes = semicolon_suffixes or {}

    def __getattr__(self, name: str) -> Any:
        # Delegate all other attribute access to the wrapped transform
        return getattr(self.transform, name)

    def __repr__(self) -> str:
        if self.start_lineno == self.end_lineno:
            return f"<_LocalImportBlockWrapper lineno={self.start_lineno} {self.transform!r}>"
        else:
            return f"<_LocalImportBlockWrapper lines={self.start_lineno}-{self.end_lineno} {self.transform!r}>"

    def get_removed_imports(self) -> set[Import]:
        """Return the set of imports that have been removed from this block."""
        current_imports = set(self.transform.importset.imports)
        removed = self._original_imports - current_imports
        logger.debug("get_removed_imports on block %s: removed=%r", self._id, removed)
        return removed

class NoImportBlockError(Exception):
    pass

class ImportAlreadyExistsError(Exception):
    pass


def _is_future_only_import_block(block: SourceToSourceImportBlockTransformation) -> bool:
    imports = block.importset.imports
    return bool(imports) and all(imp.split.module_name == "__future__" for imp in imports)


def _maybe_insert_pass(
    lines: list[str], idx: int, indent: int, lineno: int
) -> None:
    """Insert a ``pass`` statement at *idx* when removing a line would leave a
    block-opener (a line ending with ``:``) without a body.

    After a line has been deleted at position *idx*, this function walks
    backwards to find the nearest non-empty preceding line.  If that line ends
    with ``:`` (a compound-statement header such as ``def``, ``class``,
    ``if``, etc.) and the next non-empty line after *idx* is at an equal or
    lower indentation level, the block body is gone and a ``pass`` statement
    is inserted at *idx* using *indent* spaces.

    :param lines: Source lines of the block, already modified (the import line
        has been deleted before this call).
    :param idx: Index into *lines* where the deleted line used to be.
    :param indent: Column offset (number of leading spaces) of the deleted line,
        used to indent the inserted ``pass``.
    :param lineno: Absolute line number in the file (used only for logging).
    """
    prev_idx = idx - 1
    while prev_idx >= 0 and lines[prev_idx].strip() == "":
        prev_idx -= 1
    if prev_idx < 0:
        return
    prev_line = lines[prev_idx]
    if not prev_line.rstrip().endswith(":"):
        return
    prev_indent = len(prev_line) - len(prev_line.lstrip())
    next_idx = idx
    while next_idx < len(lines) and lines[next_idx].strip() == "":
        next_idx += 1
    body_gone = (
        next_idx >= len(lines)
        or (len(lines[next_idx]) - len(lines[next_idx].lstrip())) <= prev_indent
    )
    if body_gone:
        lines.insert(idx, " " * indent + "pass")
        logger.debug("Inserted 'pass' at line %d to preserve empty block", lineno)


class SourceToSourceFileImportsTransformation(SourceToSourceTransformationBase):
    blocks: list[Union[SourceToSourceImportBlockTransformation, SourceToSourceTransformation]]
    import_blocks: list[Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]]
    _pending_local_removals: list[tuple[Import, int]]
    _original_block_startpos: dict[int, int]
    tidy_local_imports: bool = False

    def preprocess(self) -> None:
        # Group into blocks of imports and non-imports.  Get a sequence of all
        # imports for the transformers to operate on.
        self.blocks: list[Union[SourceToSourceImportBlockTransformation, SourceToSourceTransformation]] = []
        self.import_blocks: list[Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]] = []
        # Local imports removed via remove_import(); the physical edits are
        # deferred to pretty_print() so that all removals from one statement
        # can be applied together (see _apply_local_import_removals).
        self._pending_local_removals = []
        # Track original startpos for each block (before any modifications)
        self._original_block_startpos = {}

        for is_imports, subblock in self.input.groupby(lambda ps: ps.is_import):
            if is_imports:
                import_trans = SourceToSourceImportBlockTransformation(subblock)
                self.import_blocks.append(import_trans)
                self.blocks.append(import_trans)
            else:
                trans = SourceToSourceTransformation(subblock)
                self.blocks.append(trans)

        # Store original startpos for each block
        for idx, block in enumerate(self.blocks):
            if isinstance(block, SourceToSourceTransformation):
                self._original_block_startpos[idx] = block._output.startpos.lineno

        # Extract local import blocks from function/class bodies (if enabled)
        if self.tidy_local_imports:
            self._extract_local_import_blocks()
        logger.debug("preprocess: extracted %d total import blocks", len(self.import_blocks))

    def _create_import_block_from_group(
        self,
        group: list[Union[ast.Import, ast.ImportFrom]],
        lines: list[str],
        start_line: int,
        end_line: int,
    ) -> None:
        """Create an import block from a group of import statements.

        Extracts the import lines from source text, creates a PythonBlock and
        transformation, and adds it to import_blocks (wrapped with line metadata).

        Parameters
        ----------
        group : list[ast.Import | ast.ImportFrom]
            Consecutive import AST nodes to extract.
        lines : list[str]
            All source lines of the file (1-indexed via ``lines[lineno - 1]``).
        start_line : int
            First line number of the group (1-indexed).
        end_line : int
            Last line number of the group, accounting for multiline imports.
        """
        import_text_parts = []
        semicolon_suffixes = {}

        for node in group:
            lineno = node.lineno
            end_lineno = getattr(node, "end_lineno", lineno)

            if hasattr(node, "col_offset") and hasattr(node, "end_col_offset"):
                # WARNING: col_offset/end_col_offset are in bytes, not characters.
                if end_lineno > lineno:
                    # Multiline import (e.g. "from foo import (\n    a,\n    b\n)").
                    # end_col_offset refers to the last line, not the first, so we
                    # must collect all source lines and trim each end independently.
                    first = lines[lineno - 1].encode()
                    last = lines[end_lineno - 1].encode()
                    node_lines = [first[node.col_offset :].decode()]
                    for mid in range(lineno + 1, end_lineno):
                        node_lines.append(lines[mid - 1])
                    node_lines.append(last[: node.end_col_offset].decode())
                    import_stmt = "\n".join(node_lines)
                    remaining = last[node.end_col_offset :].decode().lstrip()
                else:
                    line: str = lines[lineno - 1]
                    import_stmt = line.encode()[
                        node.col_offset : node.end_col_offset
                    ].decode()
                    remaining = line.encode()[node.end_col_offset :].decode().lstrip()

                if remaining.startswith(";"):
                    suffix = remaining[1:].lstrip()
                    if suffix:
                        semicolon_suffixes[lineno] = suffix
            else:
                import_stmt = lines[lineno - 1]

            import_text_parts.append(import_stmt)

        if import_text_parts and any(part.strip() for part in import_text_parts):
            import_text = "\n".join(import_text_parts)
            try:
                import_block = PythonBlock(import_text)
                trans = SourceToSourceImportBlockTransformation(import_block)
            except (SyntaxError, ValueError, NonImportStatementError) as e:
                logger.debug(
                    "Failed to create import block for lines %d-%d: %s",
                    start_line,
                    end_line,
                    e,
                )
            else:
                wrapped = _LocalImportBlockWrapper(
                    trans, start_line, end_line, semicolon_suffixes=semicolon_suffixes
                )
                self.import_blocks.append(wrapped)

    def _extract_local_import_blocks(self) -> None:
        """
        Recursively extract import blocks from function and class bodies.
        This allows us to find and remove unused imports within functions/classes.
        """
        for block in self.blocks:
            if not isinstance(block, SourceToSourceTransformation):
                continue
            # Check each statement for function/class definitions
            for stmt in block.input.statements:
                self._extract_imports_from_statement(stmt)

    def _extract_imports_from_statement(
        self, stmt: Union[PythonStatement, ast.AST]
    ) -> None:
        """
        Recursively extract imports from a statement's body (e.g., FunctionDef, ClassDef).
        """
        if isinstance(stmt, PythonStatement):
            ast_node = stmt.ast_node
            if ast_node is None:
                # stmt.ast_node can be None for comments.
                return
        else:
            ast_node = stmt

        if not isinstance(ast_node, _FUNCTION_OR_CLASS_TYPES):
            return

        body = ast_node.body if hasattr(ast_node, "body") else []

        # Group consecutive import statements
        import_groups = _group_consecutive_imports(body)

        # For each group of consecutive imports, create an import block
        full_text = str(self.input.text)
        lines = full_text.split("\n")

        for group in import_groups:
            group_no_ignore_pragma = [
                node
                for node in group
                if not _has_ignore_pragma(
                    lines, node.lineno, getattr(node, "end_lineno", node.lineno)
                )
            ]
            if not group_no_ignore_pragma:
                continue
            start_line = group_no_ignore_pragma[0].lineno
            end_line = getattr(group[-1], "end_lineno", group[-1].lineno)
            self._create_import_block_from_group(
                group_no_ignore_pragma, lines, start_line, end_line
            )

        # Recursively check nested function/class definitions
        for body_item in body:
            if isinstance(body_item, _FUNCTION_OR_CLASS_TYPES):
                self._extract_imports_from_statement(body_item)

    def pretty_print(self, params: Any = None) -> FileText:
        params = ImportFormatParams(params)
        # Apply deferred local-import removals before rendering the blocks.
        self._apply_local_import_removals(params)
        result = [block.pretty_print(params=params) for block in self.blocks]
        output = FileText.concatenate(result)

        # Handle removal of local imports from function/class bodies
        output = self._remove_local_imports_from_output(output)

        # Handle semicolons in import statements
        output = self._split_semicolon_chained_imports(output)

        return output

    def _split_semicolon_chained_imports(self, output: FileText) -> FileText:
        """
        Split semicolon-chained import statements into separate lines.

        For local import blocks that have semicolon_suffixes (code after
        semicolons), replace those lines with the import on one line and the
        remaining code on the next.
        """
        if not self.import_blocks:
            return output

        input_lines = str(self.input.text).split("\n")

        lines_to_split = {}

        for block in self.import_blocks:
            if not isinstance(block, _LocalImportBlockWrapper):
                continue

            if not block._semicolon_suffixes:
                continue

            for lineno, suffix in block._semicolon_suffixes.items():
                lines_to_split[lineno] = suffix

        if not lines_to_split:
            return output

        logger.debug(
            "Splitting semicolon-chained imports on lines: %s",
            sorted(lines_to_split.keys()),
        )

        new_output_lines = []
        for i, line in enumerate(output.lines):
            matched_lineno = None
            line_stripped = line.strip()

            for lineno, suffix in lines_to_split.items():
                if lineno <= len(input_lines):
                    original_line = input_lines[lineno - 1].strip()
                    if line_stripped == original_line or (
                        line_stripped
                        and original_line.startswith(line_stripped.split(";")[0])
                    ):
                        matched_lineno = lineno
                        break

            if matched_lineno:
                indent_match = re.match(r"^(\s*)", line)
                indent = indent_match.group(1) if indent_match else ""

                if ";" in line:
                    parts = line.split(";", 1)
                    import_part = parts[0].rstrip()
                    new_output_lines.append(import_part)
                else:
                    new_output_lines.append(line)
                new_output_lines.append(indent + lines_to_split[matched_lineno])
            else:
                new_output_lines.append(line)

        return FileText("\n".join(new_output_lines))

    def _remove_local_imports_from_output(self, output: FileText) -> FileText:
        """
        Post-process the output to remove local imports that have been deleted.

        This is necessary because local imports are embedded in function bodies,
        which are stored in self.blocks as plain text. When we remove imports from
        local import blocks, we need to also remove those lines from the output.
        """
        # Collect all imports that need to be removed, mapped by line number
        lines_to_remove = set()

        for block in self.import_blocks:
            if not isinstance(block, _LocalImportBlockWrapper):
                continue

            logger.debug(
                "Checking local block %s at lines %d-%d",
                block._id,
                block.start_lineno,
                block.end_lineno,
            )
            removed_imports = block.get_removed_imports()
            logger.debug("Block %s: Removed imports: %r", block._id, removed_imports)

            if not removed_imports:
                continue

            logger.debug(
                "Found %d removed imports in local block at lines %d-%d",
                len(removed_imports),
                block.start_lineno,
                block.end_lineno,
            )

            # We need to figure out which lines in the output correspond to these imports
            # The block knows its original line range, so we can map back to the source
            # For now, we'll use a simple approach: parse the original input text
            # to find which line each import was on

            # Get the original input text for this block
            original_lines = str(self.input.text).split("\n")

            # For each removed import, find its line in the original source
            for imp in removed_imports:
                logger.debug("Looking for import: %s", imp)
                # Search for the import statement in the original line range
                for lineno in range(block.start_lineno, block.end_lineno + 1):
                    if lineno <= len(original_lines):
                        line = original_lines[lineno - 1]
                        # Check if this line contains the import
                        if self._line_contains_import(line, imp):
                            logger.debug(
                                "Found import on line %d: %s", lineno, line.strip()
                            )
                            lines_to_remove.add(lineno)
                            break

        if not lines_to_remove:
            return output

        logger.debug("Removing lines: %s", sorted(lines_to_remove))

        # Filter out the lines from the output
        # The output may have been reformatted, so we can't rely on line numbers matching exactly
        # Instead, we'll filter the output by matching the lines to remove
        output_lines = str(output).split("\n")

        # Get the actual lines to remove by their content
        input_lines = str(self.input.text).split("\n")
        lines_to_remove_content = set()
        for lineno in lines_to_remove:
            if lineno <= len(input_lines):
                # Store the stripped version to match against
                line_content = input_lines[lineno - 1].strip()
                if line_content:
                    lines_to_remove_content.add(line_content)

        logger.debug("Lines to remove by content: %s", lines_to_remove_content)

        # Filter output lines by content match
        filtered_lines = []
        for line in output_lines:
            stripped = line.strip()
            # Keep the line if it's not in the set of lines to remove
            if stripped not in lines_to_remove_content or not stripped:
                filtered_lines.append(line)
            else:
                logger.debug("Removing line: %s", line)

        return FileText("\n".join(filtered_lines))

    def _line_contains_import(self, line: str, imp: Import) -> bool:
        """
        Check if a line contains the given import statement.

        Parse the line as an import statement and compare Import objects,
        rather than using string matching which is fragile with spacing.
        """
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return False

        try:
            # Parse the line as an import statement
            stmt = ImportStatement._from_str(stripped)
            # Check if any of the imports in this statement match the target import
            for line_import in stmt.imports:
                if line_import == imp:
                    return True
        except (SyntaxError, ValueError):
            # Line is not a valid import statement
            pass

        return False

    def find_import_block_by_lineno(self, lineno: int) -> Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]:
        """
        Find the import block containing the given line number.

        Handles both top-level and local (function/class) import blocks.
        For local imports wrapped in _LocalImportBlockWrapper, checks the original line range.
        For regular imports, checks the line number range.

        :type lineno:
          ``int``
        :rtype:
          `SourceToSourceImportBlockTransformation` or `_LocalImportBlockWrapper`
        """
        results: list[Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]] = []
        for b in self.import_blocks:
            # Check if this is a wrapped local import block
            if isinstance(b, _LocalImportBlockWrapper):
                # For wrapped blocks, check if lineno is in the original range
                if b.start_lineno <= lineno <= b.end_lineno:
                    results.append(b)
            else:
                # For regular blocks, check the range
                if b.input.startpos.lineno <= lineno <= b.input.endpos.lineno:
                    results.append(b)

        if len(results) == 0:
            raise LineNumberNotFoundError(lineno)
        if len(results) > 1:
            raise LineNumberAmbiguousError(lineno)
        return results[0]

    def remove_import(self, imp: Import, lineno: Any) -> Import:
        """
        Remove the given import.

        :type imp:
          `Import`
        :type lineno:
          ``int``
        """
        block = self.find_import_block_by_lineno(lineno)

        try:
            imports = block.importset.by_import_as[imp.import_as]
        except KeyError:
            raise NoSuchImportError
        assert len(imports)
        if len(imports) > 1:
            raise Exception("Multiple imports to remove: %r" % (imports,))
        imp = imports[0]
        block.importset = block.importset.without_imports([imp])

        if isinstance(block, _LocalImportBlockWrapper):
            # For local imports the source text must be edited.  Defer the
            # edit until pretty_print() so that all removals targeting the
            # same statement are applied in one rewrite.
            self._pending_local_removals.append((imp, lineno))

        return imp

    def _apply_local_import_removals(self, params: ImportFormatParams) -> None:
        """
        Apply the local-import removals recorded by ``remove_import``.

        The removals are grouped by (block, statement start line) so that all
        aliases removed from one statement are handled in a single rewrite,
        and statements are processed bottom-up within each block so that
        edits never shift the line numbers of statements not yet processed.

        :param params:
          Formatting parameters used to re-wrap the surviving local imports,
          so that options like ``--width`` apply to local imports just as they
          do to top-level ones.
        """
        if not self._pending_local_removals:
            return
        pending = self._pending_local_removals
        self._pending_local_removals = []

        # Group the removals by containing block, then by statement start line.
        by_block: Dict[int, Dict[int, List[Import]]] = defaultdict(
            lambda: defaultdict(list))
        for imp, lineno in pending:
            for block_idx, block in enumerate(self.blocks):
                if not isinstance(block, SourceToSourceTransformation):
                    continue
                original_startpos = self._original_block_startpos.get(
                    block_idx, block._output.startpos.lineno
                )
                if original_startpos <= lineno <= block._output.endpos.lineno:
                    by_block[block_idx][lineno].append(imp)
                    break
            else:
                logger.warning(
                    "Couldn't find block containing line %d to remove %r",
                    lineno, imp)

        for block_idx, by_lineno in by_block.items():
            block = self.blocks[block_idx]
            assert isinstance(block, SourceToSourceTransformation)
            lines = str(block._output.text).split("\n")
            original_startpos = self._original_block_startpos.get(
                block_idx, block._output.startpos.lineno
            )
            for lineno in sorted(by_lineno, reverse=True):
                lines = self._rewrite_local_import_statement(
                    lines, lineno - original_startpos, by_lineno[lineno],
                    lineno, params)
            block._output = PythonBlock(
                "\n".join(lines), filename=block._output.filename
            )

    def _rewrite_local_import_statement(
        self, lines: List[str], rel: int, imps: List[Import], lineno: int,
        params: ImportFormatParams
    ) -> List[str]:
        """
        Rewrite the import statement starting at ``lines[rel]`` with the
        imports in ``imps`` removed.  Co-located code -- other aliases in the
        same statement, semicolon-separated statements on the same line,
        parenthesized continuation lines -- is preserved; the physical lines
        are deleted only when nothing else remains on them.

        :param lines:
          Source lines of the block.  This list is not modified; the rewritten
          lines are returned instead.
        :param rel:
          Index into ``lines`` of the first line of the import statement.
        :param imps:
          The `Import` s to remove from the statement.
        :param lineno:
          Absolute line number in the file (for logging).
        :param params:
          Formatting parameters.  When the import occupies its own line(s),
          the surviving statement is re-wrapped according to these parameters
          (e.g. ``--width``).
        :return:
          A new list of lines with the rewrite applied.  When nothing can be
          rewritten (e.g. the statement can't be parsed), a copy of the
          original ``lines`` is returned unchanged.
        """
        # Work on a copy so the caller's list is never mutated in place.
        lines = list(lines)
        if not (0 <= rel < len(lines)):
            logger.warning(
                "Line %d out of range (relative %d, %d lines in block)",
                lineno, rel, len(lines))
            return lines
        first_line = lines[rel]
        indent_str = first_line[: len(first_line) - len(first_line.lstrip())]
        # Find the physical extent of the statement: extend line by line until
        # the candidate text parses (handles parenthesized multiline imports
        # and backslash continuations).
        module = None
        end = rel
        for end in range(rel, len(lines)):
            candidate = "\n".join([first_line.lstrip()] + lines[rel + 1: end + 1])
            try:
                module = ast.parse(candidate)
            except SyntaxError:
                continue
            break
        if module is None:
            logger.warning(
                "Couldn't parse statement at line %d; leaving it untouched",
                lineno)
            return lines
        src_lines = candidate.split("\n")
        # Find the import node containing the imports to remove.  (The line
        # may hold several semicolon-separated statements.)
        target = None
        target_stmt = None
        matched: List[Import] = []
        for node in module.body:
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            stmt = ImportStatement._from_ast_node(node)
            matched = [imp for imp in imps if imp in stmt.imports]
            if matched:
                target = node
                target_stmt = stmt
                break
        if target is None or target_stmt is None:
            logger.warning(
                "Couldn't find import(s) %s at line %d; leaving line untouched",
                ", ".join(map(str, imps)), lineno)
            return lines
        remaining = [imp for imp in target_stmt.imports if imp not in matched]
        # Splice the rewritten statement between the text surrounding it.
        # WARNING: col_offset/end_col_offset are in bytes, not characters.
        assert target.lineno is not None
        assert target.end_lineno is not None
        prefix = (src_lines[target.lineno - 1]
                  .encode()[: target.col_offset].decode())
        suffix = (src_lines[target.end_lineno - 1]
                  .encode()[target.end_col_offset:].decode())
        if remaining and not prefix.strip() and not suffix.strip():
            width = params.max_line_length
            if width is None:
                width = params.max_line_length_default
            sub_params = ImportFormatParams(
                params, max_line_length=max(width - len(indent_str), 1))
            rendered = ImportStatement._from_imports(remaining).pretty_print(
                sub_params).rstrip("\n")
            lines[rel: end + 1] = [
                indent_str + line if line else line
                for line in rendered.split("\n")
            ]
            return lines
        if remaining:
            new_text = (
                prefix + str(ImportStatement._from_imports(remaining)) + suffix)
        else:
            before = prefix.rstrip()
            after = suffix.lstrip()
            # Drop the semicolon that used to join the import to its neighbor.
            if before.endswith(";"):
                before = before[:-1].rstrip()
            elif after.startswith(";"):
                after = after[1:].lstrip()
            if before and after:
                new_text = before + "; " + after
            else:
                new_text = before or after
        if new_text.strip():
            lines[rel: end + 1] = [indent_str + new_text]
        else:
            del lines[rel: end + 1]
            _maybe_insert_pass(lines, rel, len(indent_str), lineno)
        return lines

    def select_import_block_by_closest_prefix_match(
        self, imp: Import, max_lineno: Union[int, float]
    ) -> SourceToSourceImportBlockTransformation:
        """
        Heuristically pick an import block that ``imp`` "fits" best into.  The
        selection is based on the block that contains the import with the
        longest common prefix.

        :type imp:
          `Import`
        :param max_lineno:
          Only return import blocks earlier than ``max_lineno``.
        :rtype:
          `SourceToSourceImportBlockTransformation`
        """
        # Create a data structure that annotates blocks with data by which
        # we'll sort.  Only consider global import blocks, not local ones
        # (wrapped in _LocalImportBlockWrapper), since new imports should
        # always be added at the module level.
        annotated_blocks = [
            ( (max([0] + [len(imp.prefix_match(oimp))
                          for oimp in block.importset.imports]),
               block.input.endpos.lineno),
              block )
            for block in self.import_blocks
            if not isinstance(block, _LocalImportBlockWrapper)
            and block.input.endpos.lineno <= max_lineno+1
            and (
                imp.split.module_name == "__future__"
                or not _is_future_only_import_block(block)
            ) ]
        if not annotated_blocks:
            raise NoImportBlockError()
        annotated_blocks.sort(key=lambda x: x[0])
        if imp.split.module_name == '__future__':
            # For __future__ imports, only add to an existing block that
            # already contains __future__ import(s).  If there are no existing
            # import blocks containing __future__, don't return any result
            # here, so that we will add a new one at the top.
            if not annotated_blocks[-1][0][0] > 0:
                raise NoImportBlockError
        return annotated_blocks[-1][1]

    def insert_new_blocks_after_comments(self, blocks: List[Any]) -> None:
        blocks = [SourceToSourceTransformationBase(block) for block in blocks]
        if isinstance(self.blocks[0], SourceToSourceImportBlockTransformation):
            # Kludge.  We should add an "output" attribute to
            # SourceToSourceImportBlockTransformation and enumerate over that,
            # instead of enumerating over the input below.
            self.blocks[0:0] = blocks
            return
        # Get the "statements" in the first block.
        statements = self.blocks[0].input.statements
        # Find the insertion point.
        for idx, statement in enumerate(statements):
            if not statement.is_comment_or_blank_or_string_literal:
                if idx == 0:
                    # First block starts with a noncomment, so insert before
                    # it.
                    self.blocks[0:0] = blocks
                else:
                    # Found a non-comment after comment, so break it up and
                    # insert in the middle.
                    self.blocks[:1] = (
                        [SourceToSourceTransformation(
                            PythonBlock.concatenate(statements[:idx]))] +
                        blocks +
                        [SourceToSourceTransformation(
                            PythonBlock.concatenate(statements[idx:]))])
                break
        else:
            # First block is entirely comments, so just insert after it.
            self.blocks[1:1] = blocks

    def insert_new_import_block(self) -> SourceToSourceImportBlockTransformation:
        """
        Adds a new empty imports block.  It is added before the first
        non-comment statement.  Intended to be used when the input contains no
        import blocks (before uses).
        """
        block = SourceToSourceImportBlockTransformation("")
        sepblock = SourceToSourceTransformation("")
        sepblock._output = PythonBlock("\n")
        self.insert_new_blocks_after_comments([block, sepblock])
        self.import_blocks.insert(0, block)
        return block

    def insert_new_import_block_after_future_imports(self) -> SourceToSourceImportBlockTransformation:
        future_block_indexes = [
            idx
            for idx, block in enumerate(self.blocks)
            if isinstance(block, SourceToSourceImportBlockTransformation)
            and _is_future_only_import_block(block)
        ]
        if not future_block_indexes:
            return self.insert_new_import_block()

        block = SourceToSourceImportBlockTransformation("")
        sepblock_before = SourceToSourceTransformation("")
        sepblock_before._output = PythonBlock("\n")
        insert_at = future_block_indexes[-1] + 1
        next_block = self.blocks[insert_at] if insert_at < len(self.blocks) else None
        blocks_to_insert: list[Union[SourceToSourceImportBlockTransformation, SourceToSourceTransformation]] = [
            sepblock_before,
            block,
        ]
        if not (
            isinstance(next_block, SourceToSourceTransformation)
            and str(next_block.pretty_print()).startswith("\n")
        ):
            sepblock_after = SourceToSourceTransformation("")
            sepblock_after._output = PythonBlock("\n")
            blocks_to_insert.append(sepblock_after)

        self.blocks[insert_at:insert_at] = blocks_to_insert
        future_import_block_indexes = [
            idx
            for idx, import_block in enumerate(self.import_blocks)
            if not isinstance(import_block, _LocalImportBlockWrapper)
            and _is_future_only_import_block(import_block)
        ]
        import_block_insert_at = (
            future_import_block_indexes[-1] + 1 if future_import_block_indexes else 0
        )
        self.import_blocks.insert(import_block_insert_at, block)
        return block

    def add_import(self, imp: Import, lineno: Any = Inf) -> None:
        """
        Add the specified import.  Picks an existing global import block to
        add to, or if none found, creates a new one near the beginning of the
        module.

        :type imp:
          `Import`
        :param lineno:
          Line before which to add the import.  ``Inf`` means no constraint.
        """
        try:
            block = self.select_import_block_by_closest_prefix_match(
                imp, lineno)
        except NoImportBlockError:
            if imp.split.module_name == "__future__":
                block = self.insert_new_import_block()
            else:
                block = self.insert_new_import_block_after_future_imports()
        if imp in block.importset.imports:
            raise ImportAlreadyExistsError(imp)
        block.importset = block.importset.with_imports([imp])


def reformat_import_statements(
    codeblock: Union[PythonBlock, FileText, Filename, str], params: Any = None
) -> PythonBlock:
    r"""
    Reformat each top-level block of import statements within a block of code.
    Blank lines, comments, etc. are left alone and separate blocks of imports.

    Parse the entire code block into an ast, group into consecutive import
    statements and other lines.  Each import block consists entirely of
    'import' (or 'from ... import') statements.  Other lines, including blanks
    and comment lines, are not touched.

      >>> print(reformat_import_statements(
      ...     'from foo import bar2 as bar2x, bar1\n'
      ...     'import foo.bar3 as bar3x\n'
      ...     'import foo.bar4\n'
      ...     '\n'
      ...     'import foo.bar0 as bar0\n').text.joined)
      import foo.bar4
      from foo import bar1, bar2 as bar2x, bar3 as bar3x
      <BLANKLINE>
      from foo import bar0
      <BLANKLINE>

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :type params:
      `ImportFormatParams`
    :rtype:
      `PythonBlock`
    """
    params = ImportFormatParams(params)
    original_tidy_local = SourceToSourceFileImportsTransformation.tidy_local_imports
    try:
        SourceToSourceFileImportsTransformation.tidy_local_imports = False
        transformer = SourceToSourceFileImportsTransformation(codeblock)
        return transformer.output(params=params)
    finally:
        SourceToSourceFileImportsTransformation.tidy_local_imports = original_tidy_local


def ImportPathForRelativeImportsCtx(
    codeblock: Union[PythonBlock, FileText, Filename, str]
) -> ContextManager[Any]:
    """
    Context manager that temporarily modifies ``sys.path`` so that relative
    imports for the given ``codeblock`` work as expected.

    :type codeblock:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    if not codeblock.filename:
        return nullcontext()
    if codeblock.flags & CompilerFlags("absolute_import"):
        return nullcontext()
    return ImportPathCtx(str(codeblock.filename.dir))


def fix_unused_and_missing_imports(
    codeblock: Union[PythonBlock, str, Filename],
    add_missing: bool = True,
    remove_unused: Union[Literal["AUTOMATIC"], bool] = "AUTOMATIC",
    add_mandatory: bool = True,
    db: Optional[ImportDB] = None,
    params: Any = None,
    tidy_local_imports: bool = False,
) -> PythonBlock:
    r"""
    Check for unused and missing imports, and fix them automatically.

    Also formats imports.

    By default only top-level imports are tidied.  Set ``tidy_local_imports=True``
    to also remove unused imports inside function and class bodies.

    Individual imports can be excluded from removal by adding
    ``# tidy-imports: ignore-import`` as a trailing comment.
    This is whitespace sentitive between and must be a single space after the
    `#`, and after the `:`

    In the example below, ``m1`` and ``m3`` are unused, so are automatically
    removed.  ``np`` was undefined, so an ``import numpy as np`` was
    automatically added.

      >>> codeblock = PythonBlock(
      ...     'from foo import m1, m2, m3, m4\n'
      ...     'm2, m4, np.foo', filename="/tmp/foo.py")

      >>> print(fix_unused_and_missing_imports(codeblock, add_mandatory=False))
      [PYFLYBY] /tmp/foo.py: removed unused 'from foo import m1'
      [PYFLYBY] /tmp/foo.py: removed unused 'from foo import m3'
      [PYFLYBY] /tmp/foo.py: added 'import numpy as np'
      import numpy as np
      from foo import m2, m4
      m2, m4, np.foo

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :param tidy_local_imports:
      If ``True``, also tidy imports within function and class bodies.
      Defaults to ``False``.
    :rtype:
      `PythonBlock`
    """
    _codeblock: PythonBlock
    if isinstance(codeblock, Filename):
        _codeblock = PythonBlock(codeblock)
    elif not isinstance(codeblock, PythonBlock):
        _codeblock = PythonBlock(codeblock)
    else:
        _codeblock = codeblock
    if remove_unused == "AUTOMATIC":
        fn = _codeblock.filename
        remove_unused = not (fn and
                             (fn.base == "__init__.py"
                              or ".pyflyby" in str(fn).split("/")))
    elif remove_unused is True or remove_unused is False:
        pass
    else:
        raise ValueError("Invalid remove_unused=%r" % (remove_unused,))
    params = ImportFormatParams(params)
    db = ImportDB.interpret_arg(db, target_filename=_codeblock.filename)
    # Do a first pass reformatting the imports to get rid of repeated or
    # shadowed imports, e.g. L1 here:
    #   import foo  # L1
    #   import foo  # L2
    #   foo         # L3
    _codeblock = reformat_import_statements(_codeblock, params=params)

    filename = _codeblock.filename
    # Set the tidy_local_imports flag on the class before creating an instance
    original_tidy_local = SourceToSourceFileImportsTransformation.tidy_local_imports
    try:
        SourceToSourceFileImportsTransformation.tidy_local_imports = tidy_local_imports
        transformer = SourceToSourceFileImportsTransformation(_codeblock)
    finally:
        SourceToSourceFileImportsTransformation.tidy_local_imports = original_tidy_local
    missing_imports, unused_imports = scan_for_import_issues(
        _codeblock, find_unused_imports=remove_unused, parse_docstrings=True
    )
    logger.debug("missing_imports = %r", missing_imports)
    logger.debug("unused_imports = %r", unused_imports)
    if remove_unused and unused_imports:
        # Go through imports to remove.  [This used to be organized by going
        # through import blocks and removing all relevant blocks from there,
        # but if one removal caused problems the whole thing would fail.  The
        # CPU cost of calling without_imports() multiple times isn't worth
        # that.]
        # TODO: don't remove unused mandatory imports.  [This isn't
        # implemented yet because this isn't necessary for __future__ imports
        # since they aren't reported as unused, and those are the only ones we
        # have by default right now.]
        for item in unused_imports:
            # Each item is a (lineno, imp, scope_name) tuple
            lineno, imp, scope_name = item

            try:
                imp = transformer.remove_import(imp, lineno)
            except NoSuchImportError:
                logger.error(
                    "%s: couldn't remove import %r", filename, imp,)
            except LineNumberNotFoundError as e:
                logger.debug(
                    "%s: unused import %r on line %d not global",
                    filename, str(imp), e.args[0])
            else:
                # Report with scope context if available
                if scope_name:
                    logger.info(
                        "%s:%d: removed unused '%s' in %s '%s'",
                        filename,
                        lineno,
                        imp,
                        "function" if scope_name else "scope",
                        scope_name,
                    )
                else:
                    logger.info("%s: removed unused '%s'", filename, imp)

    if add_missing and missing_imports:
        missing_imports.sort(key=lambda k: (k[1], k[0]))
        known = db.known_imports.by_import_as
        # Decide on where to put each import to be added.  Find the import
        # block with the longest common prefix.  Tie-break by preferring later
        # blocks.
        added_imports = set()
        for lineno, ident in missing_imports:
            import_as = ident.parts[0]
            try:
                imports = known[import_as]
            except KeyError:
                logger.warning(
                    "%s:%s: undefined name %r and no known import for it",
                    filename, lineno, import_as)
                continue
            if len(imports) != 1:
                logger.error("%s: don't know which of %r to use",
                             filename, imports)
                continue
            imp_to_add = imports[0]
            if imp_to_add in added_imports:
                continue
            transformer.add_import(imp_to_add, lineno)
            added_imports.add(imp_to_add)
            logger.info("%s: added %r", filename,
                        imp_to_add.pretty_print().strip())

    if add_mandatory:
        # Todo: allow not adding to empty __init__ files?
        mandatory = db.mandatory_imports.imports
        for imp in mandatory:
            try:
                transformer.add_import(imp)
            except ImportAlreadyExistsError:
                pass
            else:
                logger.info("%s: added mandatory %r",
                            filename, imp.pretty_print().strip())

    return transformer.output(params=params)


def remove_broken_imports(
    codeblock: Union[PythonBlock, FileText, Filename, str], params: Any = None
) -> PythonBlock:
    """
    Try to execute each import, and remove the ones that don't work.

    Also formats imports.

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :rtype:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    filename = codeblock.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        broken: List[Import] = []
        for imp in list(block.importset.imports):
            ns: Dict[str, Any] = {}
            try:
                exec(imp.pretty_print(), ns)
            except Exception as e:
                logger.info("%s: Could not import %r; removing it: %s: %s",
                            filename, imp.fullname, type(e).__name__, e)
                broken.append(imp)
        block.importset = block.importset.without_imports(broken)
    return transformer.output(params=params)


def replace_star_imports(
    codeblock: Union[PythonBlock, FileText, Filename, str], params: Any = None
) -> PythonBlock:
    r"""
    Replace lines such as::

      from foo.bar import *
    with
      from foo.bar import f1, f2, f3

    Note that this requires involves actually importing ``foo.bar``, which may
    have side effects.  (TODO: rewrite to avoid this?)

    The result includes all imports from the ``email`` module.  The result
    excludes shadowed imports.  In this example:

        1. The original ``MIMEAudio`` import is shadowed, so it is removed.
        2. The ``MIMEImage`` import in the ``email`` module is shadowed by a
           subsequent import, so it is omitted.

        >>> codeblock = PythonBlock('from keyword import *', filename="/tmp/x.py")

        >>> print(replace_star_imports(codeblock)) # doctest: +SKIP
        [PYFLYBY] /tmp/x.py: replaced 'from keyword import *' with 2 imports
        from keyword import iskeyword, kwlist
        <BLANKLINE>

    Usually you'll want to remove unused imports after replacing star imports.

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :rtype:
      `PythonBlock`
    """
    from pyflyby._modules import ModuleHandle
    params = ImportFormatParams(params)
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    filename = codeblock.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        # Iterate over the import statements in ``block.input``.  We do this
        # instead of using ``block.importset`` because the latter doesn't
        # preserve the order of inputs.  The order is important for
        # determining what's shadowed.
        imports = [
            imp
            for s in block.input.statements
            for imp in ImportStatement(s).imports
        ]
        # Process "from ... import *" statements.
        new_imports = []
        for imp in imports:
            if imp.split.member_name != "*":
                new_imports.append(imp)
            elif imp.split.module_name.startswith("."):
                # The source contains e.g. "from .foo import *".  Right now we
                # don't have a good way to figure out the absolute module
                # name, so we can't get at foo.  That said, there's a decent
                # chance that this is inside an __init__ anyway, which is one
                # of the few justifiable use cases for star imports in library
                # code.
                logger.warning("%s: can't replace star imports in relative import: %s",
                               filename, imp.pretty_print().strip())
                new_imports.append(imp)
            else:
                module = ModuleHandle(imp.split.module_name)
                try:
                    with ImportPathForRelativeImportsCtx(codeblock):
                        exports = module.exports
                except Exception as e:
                    logger.warning(
                        "%s: couldn't import '%s' to enumerate exports, "
                        "leaving unchanged: '%s'.  %s: %s",
                        filename, module.name, imp, type(e).__name__, e)
                    new_imports.append(imp)
                    continue
                if not exports:
                    # We found nothing in the target module.  This probably
                    # means that module itself is just importing things from
                    # other modules.  Currently we intentionally exclude those
                    # imports since usually we don't want them.  TODO: do
                    # something better here.
                    logger.warning("%s: found nothing to import from %s, "
                                   "leaving unchanged: '%s'",
                                   filename, module, imp)
                    new_imports.append(imp)
                else:
                    new_imports.extend(exports)
                    logger.info("%s: replaced %r with %d imports", filename,
                                imp.pretty_print().strip(), len(exports))
        block.importset = ImportSet(new_imports, ignore_shadowed=True)
    return transformer.output(params=params)


class _NoImportBlockTransformer:
    """
    AST-aware textual rewriter for a single block of (non-top-level-import)
    code.  See `_transform_noimport_block` for the behavior contract.

    All state is set up in `__init__`; call `run` once to produce the rewritten
    `PythonBlock`.
    """

    # Map of dotted-name prefixes to their replacements, e.g. {"a.b": "x.y"}.
    _transformations: _Transformations
    # Whether to also rewrite inside string literals.
    _transform_strings: bool
    # The (position-normalized) block being transformed.
    _block: PythonBlock
    # ``_transformations`` with keys pre-split into components, longest first.
    _key_specs: list[tuple[tuple[str, ...], str]]
    # UTF-8 encoding of the block source; edits splice on bytes.
    _data: bytes
    # Byte offset of the start of each (1-based) line.
    _line_starts: list[int]
    # Pending edits as (start_byte, end_byte, replacement_bytes).
    _edits: list[tuple[int, int, bytes]]

    def __init__(
        self,
        block: PythonBlock,
        transformations: _Transformations,
        transform_strings: bool,
    ) -> None:
        self._transformations = transformations
        self._transform_strings = transform_strings
        # Re-wrap so the AST node positions start at line 1 / column 0,
        # regardless of where this block sits in the original file (a
        # sub-block's ``ast_node`` otherwise reports absolute, file-relative
        # line numbers).  ``PythonBlock`` dedents the source before parsing, so
        # the resulting ``ast_node`` positions are relative to the *dedented*
        # text; dedent here too so that ``_data``/``_line_starts`` (which we
        # splice against using those positions) stay in sync.  For normal
        # top-level blocks the first line is already at column 0 and dedent is
        # a no-op.
        source = dedent(block.text.joined)
        self._block = PythonBlock(source, flags=block.flags)
        if not self._block.parsable:
            raise SyntaxError(
                "transform_imports: could not parse code block:\n%s" % (source,)
            )
        # Pre-split keys into components for component-wise prefix matching,
        # longest first so the most specific transformation wins.
        self._key_specs = sorted(
            ((tuple(k.split(".")), v) for k, v in transformations.items()),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
        self._data = source.encode("utf-8")
        # Byte offset of the start of each (1-based) line.  ``ast`` reports
        # ``col_offset`` as a UTF-8 byte offset, so we splice on bytes.
        self._line_starts = [0]
        for i, byte in enumerate(self._data):
            # Iterating ``bytes`` yields ``int``; compare to the newline ordinal.
            if byte == ord(b"\n"):
                self._line_starts.append(i + 1)
        self._edits = []

    def run(self) -> PythonBlock:
        """
        Walk the AST collecting edits, then apply them and return the
        rewritten block.  Returns the (re-wrapped) input unchanged if no
        references matched.
        """
        self._visit(self._block.ast_node)
        if not self._edits:
            return self._block
        # Apply edits right-to-left so earlier byte offsets stay valid.
        self._edits.sort(key=lambda e: e[0], reverse=True)
        out = self._data
        for start, end, replacement in self._edits:
            out = out[:start] + replacement + out[end:]
        return PythonBlock(out.decode("utf-8"), flags=self._block.flags)

    def _regex_replace(self, text: str) -> str:
        """
        Apply each transformation to ``text`` as a word-boundary regex
        substitution.  Used for spans that contain only dotted names (local
        imports) or that we deliberately rewrite verbatim (strings).
        """
        for k, v in self._transformations.items():
            text = re.sub(r"\b%s\b" % (re.escape(k),), v, text)
        return text

    def _abspos(self, lineno: int, col_offset: int) -> int:
        """Return the absolute byte offset of a (1-based ``lineno``,
        ``col_offset``) AST position."""
        return self._line_starts[lineno - 1] + col_offset

    def _match_key(
        self,
        components: list[str],
    ) -> Optional[tuple[tuple[str, ...], str]]:
        """
        Return the (components, replacement) of the longest transformation key
        that is a component-wise prefix of ``components``, or None if none
        matches.
        """
        for kc, v in self._key_specs:
            if len(kc) <= len(components) and tuple(components[: len(kc)]) == kc:
                return kc, v
        return None

    def _node_start(self, node: Union[ast.stmt, ast.expr]) -> int:
        """Return the absolute byte offset of ``node``'s start position."""
        return self._abspos(node.lineno, node.col_offset)

    def _node_end(self, node: Union[ast.stmt, ast.expr]) -> int:
        """Return the absolute byte offset of ``node``'s end position."""
        # Nodes parsed from source always carry end positions.
        assert node.end_lineno is not None and node.end_col_offset is not None
        return self._abspos(node.end_lineno, node.end_col_offset)

    def _add_regex_edit(self, node: Union[ast.stmt, ast.expr]) -> None:
        """Queue a `_regex_replace` rewrite over ``node``'s own source span."""
        start = self._node_start(node)
        end = self._node_end(node)
        chunk = self._regex_replace(self._data[start:end].decode("utf-8"))
        self._edits.append((start, end, chunk.encode("utf-8")))

    def _add_name_edit(
        self,
        node: Union[ast.stmt, ast.expr],
        end_node: Union[ast.stmt, ast.expr],
        v: str,
    ) -> None:
        """Queue a replacement of the span from ``node``'s start through
        ``end_node``'s end with the literal ``v``."""
        start = self._node_start(node)
        end = self._node_end(end_node)
        self._edits.append((start, end, v.encode("utf-8")))

    def _handle_attribute_chain(self, node: ast.Attribute) -> None:
        """
        Rewrite a head-anchored dotted-name reference.  ``node`` is the
        outermost `ast.Attribute` of a chain; if the chain's base is not a bare
        name, recurse into it instead.
        """
        attrs_top_to_bottom = []
        n: ast.AST = node
        while isinstance(n, ast.Attribute):
            attrs_top_to_bottom.append(n)
            n = n.value
        if not isinstance(n, ast.Name):
            # The chain doesn't start at a bare name (e.g. ``f().bar`` or
            # ``(a + b).c``); recurse into the base for nested references.
            self._visit(n)
            return
        head = n
        attrs_bottom_to_top = attrs_top_to_bottom[::-1]
        components = [head.id] + [a.attr for a in attrs_bottom_to_top]
        m = self._match_key(components)
        if m is None:
            return
        kc, v = m
        # The matched prefix spans from the head name through the
        # (len(kc) - 1)th attribute access.
        end_node = head if len(kc) == 1 else attrs_bottom_to_top[len(kc) - 2]
        self._add_name_edit(head, end_node, v)

    def _visit(self, node: ast.AST) -> None:
        """
        Recursively walk ``node``, queuing edits for matching name references,
        attribute chains, local imports, and (when ``transform_strings``)
        string literals.
        """
        if isinstance(node, ast.Attribute):
            self._handle_attribute_chain(node)
        elif isinstance(node, ast.Name):
            m = self._match_key([node.id])
            if m is not None:
                self._add_name_edit(node, node, m[1])
        elif isinstance(node, _IMPORT_TYPES):
            # Local import; safe to rewrite textually (only dotted names).
            self._add_regex_edit(node)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if self._transform_strings:
                self._add_regex_edit(node)
        elif isinstance(node, ast.JoinedStr):
            if sys.version_info >= (3, 12):
                for value in node.values:
                    if isinstance(value, ast.FormattedValue):
                        self._visit(value.value)
                        if value.format_spec is not None:
                            self._visit(value.format_spec)
                    elif (
                        isinstance(value, ast.Constant)
                        and isinstance(value.value, str)
                        and self._transform_strings
                    ):
                        self._add_regex_edit(value)
            elif self._transform_strings:
                # Before Python 3.12, the positions of an f-string's internal
                # nodes are unreliable (PEP 701), so we can only treat the whole
                # f-string opaquely (and only when transforming strings).
                self._add_regex_edit(node)
        else:
            for child in ast.iter_child_nodes(node):
                self._visit(child)


def _transform_noimport_block(
    block: PythonBlock,
    transformations: _Transformations,
    transform_strings: bool,
) -> PythonBlock:
    """
    Apply ``transformations`` to a block of (non-top-level-import) code.

    Unlike top-level import blocks -- which are parsed and rewritten exactly --
    the rest of the code body can only be transformed heuristically.  We do so
    in an AST-aware way:

      - References to dotted names are matched head-anchored and component-wise,
        so e.g. ``foo.bar`` is rewritten in ``foo.bar`` and ``foo.bar.baz`` but
        *not* in ``x.foo.bar`` (where ``foo.bar`` is an attribute of some other
        object ``x``).
      - String literals are left alone by default, so the contents of e.g.
        ``"foo.bar"`` are not altered.  Pass ``transform_strings=True`` to
        additionally rewrite inside string literals (including docstrings and
        f-string text).
      - Comments are never modified.
      - Local (e.g. function-body) ``import`` statements are rewritten with the
        same crude textual replacement used for top-level imports; this is safe
        because import statements contain only dotted names.

    Note: on Python < 3.12 the positions of an f-string's internal nodes are
    unreliable (PEP 701), so f-strings are treated opaquely there -- their
    expression parts are not rewritten, and their text is only rewritten (as a
    whole) when ``transform_strings`` is true.  On Python >= 3.12, f-string
    expression parts are rewritten like any other code.

    See https://github.com/deshaw/pyflyby/issues/175.

    :type block:
      `PythonBlock`
    :rtype:
      `PythonBlock`
    """
    assert isinstance(block, PythonBlock), block
    return _NoImportBlockTransformer(block, transformations, transform_strings).run()


def transform_imports(
    codeblock: Union[PythonBlock, FileText, Filename, str],
    transformations: _Transformations,
    params: Any = None,
    transform_strings: bool = False,
) -> PythonBlock:
    """
    Transform imports as specified by ``transformations``.

    transform_imports() perfectly replaces all imports in top-level import
    blocks.

    For the rest of the code body, transform_imports() does an AST-aware
    replacement: references to the dotted names being transformed are rewritten,
    but string literals and comments are left alone, and attribute chains are
    only rewritten when they are head-anchored (so ``x.foo.bar`` is not
    rewritten by ``foo.bar``).  See `_transform_noimport_block` and
    https://github.com/deshaw/pyflyby/issues/175.

      >>> result = transform_imports("from m import x", {"m.x": "m.y.z"})
      >>> print(result.text.joined.strip())
      from m.y import z as x

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :type transformations:
      ``dict`` from ``str`` to ``str``
    :param transformations:
      A map of import prefixes to replace, e.g. {"aa.bb": "xx.yy"}
    :type transform_strings:
      ``bool``
    :param transform_strings:
      If true, also rewrite matches inside string literals (including
      docstrings and f-string text).  Off by default so that e.g. the contents
      of ``"foo.bar"`` are not altered.
    :rtype:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    @memoize
    def transform_import(imp: Import) -> Import:
        # Transform a block of imports.
        # TODO: optimize
        # TODO: handle transformations containing both a.b=>x and a.b.c=>y
        for k, v in transformations.items():
            imp = imp.replace(k, v)
        return imp
    # Loop over transformer blocks.
    for block in transformer.blocks:
        if isinstance(block, SourceToSourceImportBlockTransformation):
            input_imports = block.importset.imports
            output_imports = [ transform_import(imp) for imp in input_imports ]
            block.importset = ImportSet(output_imports, ignore_shadowed=True)
        else:
            block._output = _transform_noimport_block(
                block.input, transformations, transform_strings
            )
    return transformer.output(params=params)


def canonicalize_imports(
    codeblock: Union[PythonBlock, FileText, Filename, str],
    params: Any = None,
    db: Optional[ImportDB] = None,
) -> PythonBlock:
    """
    Transform ``codeblock`` as specified by ``__canonical_imports__`` in the
    global import library.

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :rtype:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    db = ImportDB.interpret_arg(db, target_filename=codeblock.filename)
    transformations = db.canonical_imports
    return transform_imports(codeblock, transformations, params=params)
