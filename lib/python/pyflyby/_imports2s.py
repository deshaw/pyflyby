# pyflyby/_imports2s.py.
# Copyright (C) 2011-2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import print_function

import ast
from   collections              import defaultdict
from   pyflyby._autoimp         import scan_for_import_issues
from   pyflyby._file            import FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._importclns      import ImportSet, NoSuchImportError
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import (Import, ImportFormatParams,
                                        ImportStatement)
from   pyflyby._log             import logger
from   pyflyby._parse           import PythonBlock, PythonStatement
from   pyflyby._util            import ImportPathCtx, Inf, NullCtx, memoize
import re

from   typing                   import Literal, Optional, Union

from   textwrap                 import indent

# AST node types for function and class definitions
_FUNCTION_OR_CLASS_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
# AST node types for import statements
_IMPORT_TYPES = (ast.Import, ast.ImportFrom)


def _group_consecutive_imports(body: list) -> list[list]:
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

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonBlock, FileText, Filename, str)):
            return cls._from_source_code(arg)
        raise TypeError("%s: got unexpected %s"
                        % (cls.__name__, type(arg).__name__))

    @classmethod
    def _from_source_code(cls, codeblock):
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

    def preprocess(self):
        pass

    def pretty_print(self, params=None):
        raise NotImplementedError

    def output(self, params=None) -> PythonBlock:
        """
        Pretty-print and return as a `PythonBlock`.

        :rtype:
          `PythonBlock`
        """
        result = self.pretty_print(params=params)
        result = PythonBlock(result, filename=self.input.filename)
        return result

    def __repr__(self):
        return f"<{self.__class__.__name__}\n{indent(str(self.pretty_print()),'    ')}\n at 0x{hex(id(self))}>"


class SourceToSourceTransformation(SourceToSourceTransformationBase):

    _output: PythonBlock

    def preprocess(self):
        assert isinstance(self.input, PythonBlock), self.input
        self._output = self.input

    def pretty_print(self, params=None):
        return self._output.text


class SourceToSourceImportBlockTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        self.importset = ImportSet(self.input, ignore_shadowed=True)

    def pretty_print(self, params=None):
        params = ImportFormatParams(params)
        return self.importset.pretty_print(params)

    def __repr__(self):
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
    start_lineno: int
    end_lineno: int
    _original_imports: set[Import]
    _id: str

    def __init__(
        self,
        transform: SourceToSourceImportBlockTransformation,
        start_lineno: int,
        end_lineno: Optional[int] = None,
    ) -> None:
        self.transform = transform
        self.start_lineno = start_lineno
        self.end_lineno = end_lineno if end_lineno is not None else start_lineno
        # Store the original imports so we can detect what was removed
        self._original_imports = set(transform.importset.imports)
        self._id = hex(id(self))

    def __getattr__(self, name: str) -> object:
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

class SourceToSourceFileImportsTransformation(SourceToSourceTransformationBase):
    blocks: list[Union[SourceToSourceImportBlockTransformation, SourceToSourceTransformation]]
    import_blocks: list[Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]]
    _removed_lines_per_block: defaultdict[int, int]
    _original_block_startpos: dict[int, int]
    tidy_local_imports: bool = True

    def preprocess(self) -> None:
        # Group into blocks of imports and non-imports.  Get a sequence of all
        # imports for the transformers to operate on.
        self.blocks: list[Union[SourceToSourceImportBlockTransformation, SourceToSourceTransformation]] = []
        self.import_blocks: list[Union[SourceToSourceImportBlockTransformation, _LocalImportBlockWrapper]] = []
        # Track removed lines per block to adjust line numbers
        self._removed_lines_per_block = defaultdict(int)
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
        self, group: list, lines: list, start_line: int, end_line: int
    ) -> None:
        """Create an import block from a group of import statements.

        Extracts the import lines from source text, creates a PythonBlock and
        transformation, and adds it to import_blocks (wrapped with line metadata).

        Parameters
        ----------
        group : list
            List of consecutive import AST nodes
        lines : list
            Lines of the full source text
        start_line : int
            Starting line number of the group
        end_line : int
            Ending line number of the group
        """
        import_lines = lines[start_line - 1 : end_line]

        if import_lines and any(line.strip() for line in import_lines):
            import_text = "\n".join(import_lines)
            try:
                import_block = PythonBlock(import_text)
                trans = SourceToSourceImportBlockTransformation(import_block)
            except (SyntaxError, ValueError) as e:
                logger.debug(
                    "Failed to create import block for lines %d-%d: %s",
                    start_line,
                    end_line,
                    e,
                )
            else:
                wrapped = _LocalImportBlockWrapper(trans, start_line, end_line)
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
            start_line = group[0].lineno
            end_line = group[-1].lineno
            self._create_import_block_from_group(group, lines, start_line, end_line)

        # Recursively check nested function/class definitions
        for body_item in body:
            if isinstance(body_item, _FUNCTION_OR_CLASS_TYPES):
                self._extract_imports_from_statement(body_item)

    def pretty_print(self, params=None):
        params = ImportFormatParams(params)
        result = [block.pretty_print(params=params) for block in self.blocks]
        output = FileText.concatenate(result)

        # Handle removal of local imports from function/class bodies
        return self._remove_local_imports_from_output(output)


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

    def remove_import(self, imp, lineno):
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
            # For local imports, we need to actually modify the source text
            # Find the block in self.blocks that contains this import and modify it
            self._remove_local_import_from_blocks(imp, lineno)

        return imp

    def _remove_local_import_from_blocks(self, imp, lineno):
        """
        Remove a local import from the actual code blocks.
        This modifies the _output of blocks in self.blocks to remove the import line.
        """
        # Find the block in self.blocks that contains this line
        for block_idx, block in enumerate(self.blocks):
            if not isinstance(block, SourceToSourceTransformation):
                continue
            # Use original startpos for comparison (before any modifications)
            original_startpos = self._original_block_startpos.get(
                block_idx, block._output.startpos.lineno
            )

            # Check against original positions
            if original_startpos <= lineno <= block._output.endpos.lineno:
                # This block contains the line, modify it
                lines = str(block._output.text).split("\n")
                logger.debug(
                    "Block originally starts at line %d, has %d lines",
                    original_startpos,
                    len(lines),
                )

                # Adjust for previously removed lines in this block
                offset = self._removed_lines_per_block[block_idx]

                # Calculate the relative line number within this block using ORIGINAL startpos
                relative_lineno = lineno - original_startpos - offset

                if 0 <= relative_lineno < len(lines):
                    line_to_remove = lines[relative_lineno]
                    logger.debug(
                        "Removing line %d (relative %d, offset %d) from block: %s",
                        lineno,
                        relative_lineno,
                        offset,
                        line_to_remove.strip(),
                    )
                    # Remove this line
                    del lines[relative_lineno]

                    # Track that we removed a line from this block
                    self._removed_lines_per_block[block_idx] = offset + 1

                    # Update the block's output
                    new_text = "\n".join(lines)
                    block._output = PythonBlock(
                        new_text, filename=block._output.filename
                    )
                else:
                    logger.warning(
                        "Line %d out of range (relative %d, %d lines in block)",
                        lineno,
                        relative_lineno,
                        len(lines),
                    )
                break

    def select_import_block_by_closest_prefix_match(self, imp, max_lineno):
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
        # we'll sort.
        annotated_blocks = [
            ( (max([0] + [len(imp.prefix_match(oimp))
                          for oimp in block.importset.imports]),
               block.input.endpos.lineno),
              block )
            for block in self.import_blocks
            if block.input.endpos.lineno <= max_lineno+1 ]
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

    def insert_new_blocks_after_comments(self, blocks):
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

    def insert_new_import_block(self):
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

    def add_import(self, imp, lineno=Inf):
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
            block = self.insert_new_import_block()
        if imp in block.importset.imports:
            raise ImportAlreadyExistsError(imp)
        block.importset = block.importset.with_imports([imp])


def reformat_import_statements(codeblock, params=None):
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
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    return transformer.output(params=params)


def ImportPathForRelativeImportsCtx(codeblock):
    """
    Context manager that temporarily modifies ``sys.path`` so that relative
    imports for the given ``codeblock`` work as expected.

    :type codeblock:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    if not codeblock.filename:
        return NullCtx()
    if codeblock.flags & CompilerFlags("absolute_import"):
        return NullCtx()
    return ImportPathCtx(str(codeblock.filename.dir))


def fix_unused_and_missing_imports(
    codeblock: Union[PythonBlock, str, Filename],
    add_missing: bool = True,
    remove_unused: Union[Literal["AUTOMATIC"], bool] = "AUTOMATIC",
    add_mandatory: bool = True,
    db: Optional[ImportDB] = None,
    params=None,
    tidy_local_imports: bool = True,
) -> PythonBlock:
    r"""
    Check for unused and missing imports, and fix them automatically.

    Also formats imports.

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


def remove_broken_imports(codeblock, params=None):
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
        broken = []
        for imp in list(block.importset.imports):
            ns = {}
            try:
                exec(imp.pretty_print(), ns)
            except Exception as e:
                logger.info("%s: Could not import %r; removing it: %s: %s",
                            filename, imp.fullname, type(e).__name__, e)
                broken.append(imp)
        block.importset = block.importset.without_imports(broken)
    return transformer.output(params=params)


def replace_star_imports(codeblock, params=None):
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


def transform_imports(codeblock, transformations, params=None):
    """
    Transform imports as specified by ``transformations``.

    transform_imports() perfectly replaces all imports in top-level import
    blocks.

    For the rest of the code body, transform_imports() does a crude textual
    string replacement.  This is imperfect but handles most cases.  There may
    be some false positives, but this is difficult to avoid.  Generally we do
    want to do replacements even within in strings and comments.

      >>> result = transform_imports("from m import x", {"m.x": "m.y.z"})
      >>> print(result.text.joined.strip())
      from m.y import z as x

    :type codeblock:
      `PythonBlock` or convertible (``str``)
    :type transformations:
      ``dict`` from ``str`` to ``str``
    :param transformations:
      A map of import prefixes to replace, e.g. {"aa.bb": "xx.yy"}
    :rtype:
      `PythonBlock`
    """
    if not isinstance(codeblock, PythonBlock):
        codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    @memoize
    def transform_import(imp):
        # Transform a block of imports.
        # TODO: optimize
        # TODO: handle transformations containing both a.b=>x and a.b.c=>y
        for k, v in transformations.items():
            imp = imp.replace(k, v)
        return imp
    def transform_block(block):
        # Do a crude string replacement in the PythonBlock.
        if not isinstance(block, PythonBlock):
            block = PythonBlock(block)
        s = block.text.joined
        for k, v in transformations.items():
            s = re.sub("\\b%s\\b" % (re.escape(k)), v, s)
        return PythonBlock(s, flags=block.flags)
    # Loop over transformer blocks.
    for block in transformer.blocks:
        if isinstance(block, SourceToSourceImportBlockTransformation):
            input_imports = block.importset.imports
            output_imports = [ transform_import(imp) for imp in input_imports ]
            block.importset = ImportSet(output_imports, ignore_shadowed=True)
        else:
            block._output = transform_block(block.input)
    return transformer.output(params=params)


def canonicalize_imports(codeblock, params=None, db=None):
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
