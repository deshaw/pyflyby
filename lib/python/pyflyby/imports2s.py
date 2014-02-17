
from __future__ import absolute_import, division, with_statement

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
        if isinstance(self.blocks[0], SourceToSourceImportBlockTransformation):
            # Kludge.  We should add an "output" attribute to
            # SourceToSourceImportBlockTransformation and enumerate over that,
            # instead of enumerating over the input below.
            self.blocks[0:0] = blocks
            return
        fblock = self.blocks[0].input
        for idx, statement in enumerate(fblock):
            if not statement.is_comment_or_blank_or_string_literal:
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


def doctests(text):
    """
    Parse doctests in string.

       >>> list(doctests(" >>> foo(bar\\n ...     + baz)\\n"))
       [PythonStatement(PythonFileLines.from_text('foo(bar\\n    + baz)\\n', linenumber=1))]

    @rtype:
      L{PythonBlock} or C{None}
    """
    import doctest
    parser = doctest.DocTestParser()
    # TODO: take into account e.lineno.
    def parse_docstring(text):
        try:
            return parser.get_examples(text)
        except Exception:
            logger.warning("Can't parse docstring, ignoring: %r", text)
            return []
    lines = [
        PythonFileLines.from_text(e.source) for e in parse_docstring(text) ]
    if lines:
        return PythonBlock(lines)
    else:
        return None


def brace_identifiers(text):
    """
    Parse a string and yield all tokens of the form "{some_token}".

      >>> list(brace_identifiers("{salutation}, {your_name}."))
      ['salutation', 'your_name']
    """
    for match in re.finditer("{([a-zA-Z_][a-zA-Z0-9_]*)}", text):
        yield match.group(1)


def _pyflakes_version():
    import pyflakes
    m = re.match("([0-9]+[.][0-9]+)", pyflakes.__version__)
    if not m:
        raise Exception(
            "Can't get pyflakes version from %r" % (pyflakes.__version__,))
    return float(m.group(1))


def _pyflakes_checker(codeblock):
    from pyflakes.checker import Checker
    codeblock = PythonBlock(codeblock)
    version = _pyflakes_version()
    if version <= 0.4:
        # pyflakes 0.4 uses the 'compiler' module.
        return Checker(codeblock.parse_tree)
    elif version >= 0.5:
        # pyflakes 0.5 uses the 'ast' module.
        return Checker(codeblock.ast)
    else:
        raise Exception("Unknown pyflakes version %r" % (version,))


def _pyflakes_find_unused_and_missing_imports(codeblock):
    """
    Find unused imports and missing imports, using Pyflakes to statically
    analyze for unused and missing imports.

    'bar' is unused and 'blah' is undefined:

      >>> find_unused_and_missing_imports("import foo as bar\\nblah\\n")
      ([('bar', 1)], [('blah', 2)])

    @type codeblock:
      L{PythonBlock} or convertible
    @return:
      C{(unused_imports, missing_imports)} where C{unused_imports} and
      C{missing_imports} each are sequences of C{(import_as, lineno)} tuples.
    """
    from pyflakes import messages as M
    codeblock = PythonBlock(codeblock)
    messages = _pyflakes_checker(codeblock).messages
    unused_imports = []
    missing_imports = []
    for message in messages:
        if isinstance(message, M.RedefinedWhileUnused):
            # Ignore redefinitions in inner scopes.
            if codeblock.split_lines[message.lineno-1].startswith(" "):
                continue
            import_as, orig_lineno = message.message_args
            unused_imports.append( (import_as, orig_lineno) )
        elif isinstance(message, M.UnusedImport):
            import_as, = message.message_args
            unused_imports.append( (import_as, message.lineno) )
        elif isinstance(message, M.UndefinedName):
            import_as, = message.message_args
            missing_imports.append( (import_as, message.lineno) )
    return unused_imports, missing_imports


def find_unused_and_missing_imports(codeblock):
    """
    Find unused imports and missing imports, taking docstrings into account.

    Pyflakes is used to statically analyze for unused and missing imports.
    Doctests in docstrings are analyzed as code and epydoc references in
    docstrings also prevent removal.

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
    codeblock = PythonBlock(codeblock)
    # Run pyflakes on the main code.
    unused_imports, missing_imports = (
        _pyflakes_find_unused_and_missing_imports(codeblock))
    # Find doctests.
    doctest_blocks = filter(None, [
            doctests(literal)
            for literal, linenumber in codeblock.string_literals() ])
    if doctest_blocks:
        # There are doctests.  Re-run pyflakes on main code + doctests.  Don't
        # report missing imports in doctests, but do treat existing imports as
        # 'used' if they are used in doctests.
        wdt_unused_imports, _ = ( # wdt = with doc tests
            _pyflakes_find_unused_and_missing_imports(
                [codeblock] + doctest_blocks))
        wdt_unused_asimports = set(
            import_as for import_as, linenumber in wdt_unused_imports)
        # Keep only the intersection of unused imports.
        unused_imports = [
            (import_as, linenumber) for import_as, linenumber in unused_imports
            if import_as in wdt_unused_asimports ]
    # Find literal brace identifiers like "... L{Foo} ...".
    literal_brace_identifiers = set(
        iden
        for literal, linenumber in codeblock.string_literals()
        for iden in brace_identifiers(literal))
    if literal_brace_identifiers:
        # Pyflakes doesn't look at docstrings containing references like
        # "L{foo}" which require an import, nor at C{str.format} strings like
        # '''"{foo}".format(...)'''.  Don't remove supposedly-unused imports
        # which match a string literal brace identifier.
        unused_imports = [
            (import_as, linenumber) for import_as, linenumber in unused_imports
            if import_as not in literal_brace_identifiers ]
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
            except LineNumberNotFoundError as e:
                logger.error(
                    "%s: unused import %r on line %d not global",
                    filename, import_as, e.args[0])
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
                logger.warning(
                    "%s:%s: undefined name %r and no known import for it",
                    filename, linenumber, import_as)
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


def remove_broken_imports(codeblock,
                          params=ImportFormatParams()):
    """
    Try to execute each import, and remove the ones that don't work.

    Also formats imports.

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      C{str}
    """
    codeblock = PythonBlock(codeblock)
    filename = codeblock[0].lines.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        broken = []
        for imp in list(block.imports.imports):
            ns = {}
            try:
                exec imp.pretty_print() in ns
            except Exception as e:
                logger.info("%s: Could not import %r; removing it: %s: %s",
                            filename, imp.fullname, type(e).__name__, e)
                broken.append(imp)
        block.imports = block.imports.without_imports(broken)
    return transformer.pretty_print(params=params)


def replace_star_imports(codeblock,
                         params=ImportFormatParams()):
    """
    Replace lines such as::
      from foo.bar import *
    with
      from foo.bar import f1, f2, f3

    Note that this requires involves actually importing C{foo.bar}, which may
    have side effects.  (TODO: rewrite to avoid this?)

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      C{str}
    """
    from .modules import Module
    codeblock = PythonBlock(codeblock)
    filename = codeblock[0].lines.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        for imp in list(block.imports.imports):
            if imp.split.member_name != "*":
                continue
            exports = Module(imp.split.module_name).exports
            block.imports = block.imports.without_imports([imp]).with_imports(
                exports)
            logger.info("%s: replaced %r with %d imports", filename,
                        imp.pretty_print().strip(), len(exports.imports))
    return transformer.pretty_print(params=params)
