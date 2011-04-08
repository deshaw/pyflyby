
from __future__ import absolute_import, division, with_statement

import ast
import re

from   pyflyby.file             import Filename
from   pyflyby.importdb         import (global_known_imports,
                                        global_mandatory_imports)
from   pyflyby.importstmt       import (ImportFormatParams, Imports,
                                        NoSuchImportError)
from   pyflyby.log              import logger
from   pyflyby.parse            import PythonBlock, PythonFileLines
from   pyflyby.util             import Inf

class SourceToSourceTransformationBase(object):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonBlock, PythonFileLines, Filename, str)):
            return cls.from_source_code(arg)
        raise TypeError

    @classmethod
    def from_source_code(cls, codeblock):
        self = object.__new__(cls)
        self.input = PythonBlock(codeblock)
        self.preprocess()
        return self

    def preprocess(self):
        pass

    def pretty_print(self, params=None):
        raise NotImplementedError


class SourceToSourceTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        self.output = self.input

    def pretty_print(self, params=None):
        return self.output.lines


class SourceToSourceImportBlockTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        self.imports = Imports(self.input)

    def pretty_print(self, params=ImportFormatParams()):
        return self.imports.pretty_print(params)


class LineNumberNotFoundError(Exception):
    pass

class LineNumberAmbiguousError(Exception):
    pass

class NoImportBlockError(Exception):
    pass

class ImportAlreadyExistsError(Exception):
    pass

class SourceToSourceFileImportsTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        # Group into blocks of imports and non-imports.  Get a sequence of all
        # imports for the transformers to operate on.
        self.blocks = []
        self.import_blocks = []
        for is_imports, subblock in self.input.groupby(lambda ps: ps.is_import):
            if is_imports:
                trans = SourceToSourceImportBlockTransformation(subblock)
                self.import_blocks.append(trans)
            else:
                trans = SourceToSourceTransformation(subblock)
            self.blocks.append(trans)

    def pretty_print(self, params=ImportFormatParams()):
        result = [block.pretty_print(params=params)
                  for block in self.blocks]
        return ''.join(result)

    def find_import_block_by_linenumber(self, linenumber):
        """
        Find the import block containing the given line number.

        @type linenumber:
          C{int}
        @rtype:
          L{SourceToSourceImportBlockTransformation}
        """
        results = [
            b
            for b in self.import_blocks
            if b.input.linenumber <= linenumber <= b.input.end_linenumber]
        if len(results) == 0:
            raise LineNumberNotFoundError(linenumber)
        if len(results) > 1:
            raise LineNumberAmbiguousError(linenumber)
        return results[0]

    def remove_import(self, import_as, linenumber):
        """
        Remove the given import.

        @type import_as:
          C{str}
        @type linenumber:
          C{int}
        """
        block = self.find_import_block_by_linenumber(linenumber)
        try:
            imports = block.imports.by_import_as[import_as]
        except KeyError:
            raise NoSuchImportError
        assert len(imports)
        if len(imports) > 1:
            raise Exception("Multiple imports to remove: %r" % (imports,))
        imp = imports[0]
        block.imports = block.imports.without_imports([imp])
        return imp

    def select_import_block_by_closest_prefix_match(self, imp, max_linenumber):
        """
        Heuristically pick an import block that C{imp} "fits" best into.  The
        selection is based on the block that contains the import with the
        longest common prefix.

        @type imp:
          L{Import}
        @param max_linenumber:
          Only return import blocks earlier than C{max_linenumber}.
        @rtype:
          L{SourceToSourceImportBlockTransformation}
        """
        # Create a data structure that annotates blocks with data by which
        # we'll sort.
        annotated_blocks = [
            ( (max([0] + [len(imp.prefix_match(oimp))
                          for oimp in block.imports.imports]),
               block.input.end_linenumber),
              block )
            for block in self.import_blocks
            if block.input.end_linenumber <= max_linenumber ]
        if not annotated_blocks:
            raise NoImportBlockError()
        annotated_blocks.sort()
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
        fblock = self.blocks[0].input
        for idx, statement in enumerate(fblock):
            if not statement.is_comment_or_blank:
                if idx == 0:
                    # First block starts with a noncomment, so insert before
                    # it.
                    self.blocks[0:0] = blocks
                else:
                    # Found a non-comment after comment, so break it up and
                    # insert in the middle.
                    self.blocks[:1] = (
                        [SourceToSourceTransformation(PythonBlock(fblock[:idx]))] +
                        blocks +
                        [SourceToSourceTransformation(PythonBlock(fblock[idx:]))])
                break
        else:
            # First block is entirely comments, so just insert after it.
            self.blocks[1:1] = blocks

    def insert_new_import_block(self):
        """
        Adds a new empty imports block.  It is added before the first
        non-comment statement.  Intended to be used when the input contains no
        import blocks (before uses).

        @type imports:
          L{Imports}
        """
        block = SourceToSourceImportBlockTransformation("")
        sepblock = SourceToSourceTransformation("")
        sepblock.output = PythonBlock("\n")
        self.insert_new_blocks_after_comments([block, sepblock])
        self.import_blocks.insert(0, block)
        return block

    def add_import(self, imp, linenumber=Inf):
        """
        Add the specified import.  Picks an existing global import block to
        add to, or if none found, creates a new one near the beginning of the
        module.

        @type imp:
          L{Import}
        @param linenumber:
          Line before which to add the import.  C{Inf} means no constraint.
        """
        try:
            block = self.select_import_block_by_closest_prefix_match(
                imp, linenumber)
        except NoImportBlockError:
            block = self.insert_new_import_block()
        if imp in block.imports.imports:
            raise ImportAlreadyExistsError(imp)
        block.imports = block.imports.with_imports([imp])


def reformat_import_statements(codeblock, params=ImportFormatParams()):
    """
    Reformat each top-level block of import statements within a block of code.
    Blank lines, comments, etc. are left alone and separate blocks of imports.

    Parse the entire code block into an ast, group into consecutive import
    statements and other lines.  Each import block consists entirely of
    'import' (or 'from ... import') statements.  Other lines, including blanks
    and comment lines, are not touched.

      >>> print reformat_import_statements(
      ...     'from foo import bar2 as bar2x, bar1\\n'
      ...     'import foo.bar3 as bar3x\\n'
      ...     'import foo.bar4\\n'
      ...     '\\n'
      ...     'import foo.bar0 as bar0\\n')
      import foo.bar4
      from foo import bar1, bar2 as bar2x, bar3 as bar3x
      <BLANKLINE>
      from foo import bar0
      <BLANKLINE>

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @type params:
      L{ImportFormatParams}
    @rtype:
      C{str}
    """
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    return transformer.pretty_print(params=params)


def string_literals(ast_node):
    """
    Yield all string literals anywhere in C{ast_node}.

      >>> list(string_literals(ast.parse("'a' + ('b' + 'c')")))
      ['a', 'b', 'c']

    @rtype:
      Generator that yields C{str}s.
    """
    for node in ast.walk(ast_node):
        for fieldname, field in ast.iter_fields(node):
            if isinstance(field, ast.Str):
                yield field.s


def brace_identifiers(text):
    """
    Parse a string and yield all tokens of the form "{some_token}".

      >>> list(brace_identifiers("{salutation}, {your_name}."))
      ['salutation', 'your_name']
    """
    for match in re.finditer("{([a-zA-Z_][a-zA-Z0-9_]*)}", text):
        yield match.group(1)


def find_unused_and_missing_imports(codeblock):
    """
    Find unused imports and missing imports.

    Pyflakes is used to statically analyze for unused and missing imports.
    Here, 'bar' is unused and 'blah' is undefined:

      >>> find_unused_and_missing_imports("import foo as bar\\nblah\\n")
      ([('bar', 1)], [('blah', 2)])

    In the following example, 'bar' is not considered unused because there is
    a string that references it in braces:

      >>> find_unused_and_missing_imports("import foo as bar, baz\\n'{bar}'\\n")
      ([('baz', 1)], [])

    @type codeblock:
      L{PythonBlock} or convertible
    @return:
      C{(unused_imports, missing_imports)} where C{unused_imports} and
      C{missing_imports} each are sequences of C{(import_as, lineno)} tuples.
    """
    from pyflakes.checker import Checker
    from pyflakes import messages as M
    codeblock = PythonBlock(codeblock)
    messages = Checker(codeblock.parse_tree).messages
    unused_imports = []
    missing_imports = []
    # Pyflakes doesn't look at docstrings containing references like "L{foo}"
    # which require an import, nor at C{str.format} strings like
    # '''"{foo}".format(...)'''.  Don't remove supposedly-unused imports which
    # match a string literal brace identifier.
    literal_brace_identifiers = set(
        iden
        for statement in codeblock if statement.ast_node
        for literal in string_literals(statement.ast_node)
        for iden in brace_identifiers(literal))
    for message in messages:
        if isinstance(message, M.RedefinedWhileUnused):
            import_as, orig_lineno = message.message_args
            if import_as not in literal_brace_identifiers:
                unused_imports.append( (import_as, orig_lineno) )
        elif isinstance(message, M.UnusedImport):
            import_as, = message.message_args
            if import_as not in literal_brace_identifiers:
                unused_imports.append( (import_as, message.lineno) )
        elif isinstance(message, M.UndefinedName):
            import_as, = message.message_args
            missing_imports.append( (import_as, message.lineno) )
    return unused_imports, missing_imports


def fix_unused_and_missing_imports(codeblock,
                                   add_missing=True,
                                   remove_unused=True,
                                   add_mandatory=True,
                                   params=ImportFormatParams()):
    """
    Using C{pyflakes}, check for unused and missing imports, and fix them
    automatically.

    Also formats imports.

    In the example below, C{m1} and C{m3} are unused, so are automatically
    removed.  C{np} was undefined, so an C{import numpy as np} was
    automatically added.

      >>> print fix_unused_and_missing_imports(
      ...     'from foo import m1, m2, m3, m4\\n'
      ...     'm2, m4, np.foo\\n', add_mandatory=False),
      import numpy as np
      from foo import m2, m4
      m2, m4, np.foo

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      C{str}
    """
    codeblock = PythonBlock(codeblock)
    filename = codeblock[0].lines.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    unused_imports, missing_imports = find_unused_and_missing_imports(codeblock)

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
        for import_as, linenumber in unused_imports:
            try:
                imp = transformer.remove_import(import_as, linenumber)
            except NoSuchImportError:
                logger.error(
                    "%s: couldn't remove import %r", filename, import_as,)
            else:
                # TODO: remove entire Import removed
                logger.info("%s: removed unused import %r",
                            filename, imp.pretty_print().strip())

    if add_missing and missing_imports:
        db = global_known_imports().by_import_as
        # Decide on where to put each import to be added.  Find the import
        # block with the longest common prefix.  Tie-break by preferring later
        # blocks.
        added_imports = set()
        for import_as, linenumber in missing_imports:
            try:
                imports = db[import_as]
            except KeyError:
                # We may want to log a message here about the unused name with
                # no known import.  However, this could be a misspelled local,
                # etc.; the user should run pyflakes normally to see all
                # messages.
                continue
            if len(imports) != 1:
                logger.error("%s: don't know which of %r to use",
                             filename, imports)
                continue
            imp_to_add = imports[0]
            if imp_to_add in added_imports:
                continue
            transformer.add_import(imp_to_add, linenumber)
            added_imports.add(imp_to_add)
            logger.info("%s: added %r", filename,
                        imp_to_add.pretty_print().strip())

    if add_mandatory:
        # Todo: allow not adding to empty __init__ files?
        db = global_mandatory_imports()
        for imp in db.imports:
            try:
                transformer.add_import(imp)
            except ImportAlreadyExistsError:
                pass
            else:
                logger.info("%s: added mandatory %r",
                            filename, imp.pretty_print().strip())

    # Pretty-print the result.
    return transformer.pretty_print(params=params)
