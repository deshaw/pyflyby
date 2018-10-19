# pyflyby/_imports2s.py.
# Copyright (C) 2011-2017 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

import re

from   pyflyby._file            import FileText, Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._idents          import brace_identifiers
from   pyflyby._importclns      import ImportSet, NoSuchImportError
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import ImportFormatParams, ImportStatement
from   pyflyby._log             import logger
from   pyflyby._parse           import PythonBlock
from   pyflyby._util            import ImportPathCtx, Inf, NullCtx, memoize
from   six                      import exec_


class SourceToSourceTransformationBase(object):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (PythonBlock, FileText, Filename, str)):
            return cls._from_source_code(arg)
        raise TypeError("%s: got unexpected %s"
                        % (cls.__name__, type(arg).__name__))

    @classmethod
    def _from_source_code(cls, codeblock):
        self = object.__new__(cls)
        self.input = PythonBlock(codeblock)
        self.preprocess()
        return self

    def preprocess(self):
        pass

    def pretty_print(self, params=None):
        raise NotImplementedError

    def output(self, params=None):
        """
        Pretty-print and return as a L{PythonBlock}.

        @rtype:
          L{PythonBlock}
        """
        result = self.pretty_print(params=params)
        result = PythonBlock(result, filename=self.input.filename)
        return result


class SourceToSourceTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        self.output = self.input

    def pretty_print(self, params=None):
        return self.output.text


class SourceToSourceImportBlockTransformation(SourceToSourceTransformationBase):
    def preprocess(self):
        self.importset = ImportSet(self.input, ignore_shadowed=True)

    def pretty_print(self, params=None):
        params = ImportFormatParams(params)
        return self.importset.pretty_print(params)


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

    def pretty_print(self, params=None):
        params = ImportFormatParams(params)
        result = [block.pretty_print(params=params) for block in self.blocks]
        return FileText.concatenate(result)

    def find_import_block_by_lineno(self, lineno):
        """
        Find the import block containing the given line number.

        @type lineno:
          C{int}
        @rtype:
          L{SourceToSourceImportBlockTransformation}
        """
        results = [
            b
            for b in self.import_blocks
            if b.input.startpos.lineno <= lineno <= b.input.endpos.lineno]
        if len(results) == 0:
            raise LineNumberNotFoundError(lineno)
        if len(results) > 1:
            raise LineNumberAmbiguousError(lineno)
        return results[0]

    def remove_import(self, import_as, lineno):
        """
        Remove the given import.

        @type import_as:
          C{str}
        @type lineno:
          C{int}
        """
        # Given a statement 'from foo import bar', older versions of pyflakes
        # report 'bar', while newer ones report 'foo.bar'.  Handle both.
        # TODO: once we move from pyflakes to our own parser, simplify this
        # logic to always take an Import or ImportStatement.
        import_as = import_as.rsplit(".", 1)[-1]
        block = self.find_import_block_by_lineno(lineno)
        try:
            imports = block.importset.by_import_as[import_as]
        except KeyError:
            raise NoSuchImportError
        assert len(imports)
        if len(imports) > 1:
            raise Exception("Multiple imports to remove: %r" % (imports,))
        imp = imports[0]
        block.importset = block.importset.without_imports([imp])
        return imp

    def select_import_block_by_closest_prefix_match(self, imp, max_lineno):
        """
        Heuristically pick an import block that C{imp} "fits" best into.  The
        selection is based on the block that contains the import with the
        longest common prefix.

        @type imp:
          L{Import}
        @param max_lineno:
          Only return import blocks earlier than C{max_lineno}.
        @rtype:
          L{SourceToSourceImportBlockTransformation}
        """
        # Create a data structure that annotates blocks with data by which
        # we'll sort.
        annotated_blocks = [
            ( (max([0] + [len(imp.prefix_match(oimp))
                          for oimp in block.importset.imports]),
               block.input.endpos.lineno),
              block )
            for block in self.import_blocks
            if block.input.endpos.lineno <= max_lineno ]
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
                            PythonBlock.concatenate(statements[:idx],
                                                    assume_contiguous=True))] +
                        blocks +
                        [SourceToSourceTransformation(
                            PythonBlock.concatenate(statements[idx:],
                                                    assume_contiguous=True))])
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
        sepblock.output = PythonBlock("\n")
        self.insert_new_blocks_after_comments([block, sepblock])
        self.import_blocks.insert(0, block)
        return block

    def add_import(self, imp, lineno=Inf):
        """
        Add the specified import.  Picks an existing global import block to
        add to, or if none found, creates a new one near the beginning of the
        module.

        @type imp:
          L{Import}
        @param lineno:
          Line before which to add the import.  C{Inf} means no constraint.
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

      >>> print reformat_import_statements(
      ...     'from foo import bar2 as bar2x, bar1\n'
      ...     'import foo.bar3 as bar3x\n'
      ...     'import foo.bar4\n'
      ...     '\n'
      ...     'import foo.bar0 as bar0\n').text.joined
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
      L{PythonBlock}
    """
    params = ImportFormatParams(params)
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    return transformer.output(params=params)


def ImportPathForRelativeImportsCtx(codeblock):
    """
    Context manager that temporarily modifies C{sys.path} so that relative
    imports for the given C{codeblock} work as expected.

    @type codeblock:
      L{PythonBlock}
    """
    codeblock = PythonBlock(codeblock)
    if not codeblock.filename:
        return NullCtx()
    if codeblock.flags & CompilerFlags("absolute_import"):
        return NullCtx()
    return ImportPathCtx(str(codeblock.filename.dir))


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
        return Checker(codeblock.ast_node)
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
            if codeblock.text[message.lineno].startswith(" "):
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
    # TODO: rewrite this using our own AST parser.
    # Once we do that we can also process doctests and literal brace
    # identifiers at the proper scope level.  We should treat both doctests
    # and literal brace identifiers as "soft" uses that don't trigger missing
    # imports but do trigger as used imports.
    codeblock = PythonBlock(codeblock)
    # Run pyflakes on the main code.
    unused_imports, missing_imports = (
        _pyflakes_find_unused_and_missing_imports(codeblock))
    # Find doctests.
    doctest_blocks = codeblock.get_doctests()
    if doctest_blocks:
        # There are doctests.  Re-run pyflakes on main code + doctests.  Don't
        # report missing imports in doctests, but do treat existing imports as
        # 'used' if they are used in doctests.
        # Create one data structure to pass to pyflakes.  This is going to
        # screw up linenos but we won't use them, so it doesn't matter.
        bigblock = PythonBlock.concatenate([codeblock] + doctest_blocks,
                                           assume_contiguous=True)
        wdt_unused_imports, _ = ( # wdt = with doc tests
            _pyflakes_find_unused_and_missing_imports(bigblock))
        wdt_unused_asimports = set(
            import_as for import_as, lineno in wdt_unused_imports)
        # Keep only the intersection of unused imports.
        unused_imports = [
            (import_as, lineno) for import_as, lineno in unused_imports
            if import_as in wdt_unused_asimports ]
    # Find literal brace identifiers like "... L{Foo} ...".
    # TODO: merge this into our own AST-based missing/unused-import-finder
    # (replacing pyflakes).
    literal_brace_identifiers = set(
        iden
        for f in codeblock.string_literals()
        for iden in brace_identifiers(f.s))
    if literal_brace_identifiers:
        # Pyflakes doesn't look at docstrings containing references like
        # "L{foo}" which require an import, nor at C{str.format} strings like
        # '''"{foo}".format(...)'''.  Don't remove supposedly-unused imports
        # which match a string literal brace identifier.
        unused_imports = [
            (import_as, lineno) for import_as, lineno in unused_imports
            if import_as not in literal_brace_identifiers ]
    return unused_imports, missing_imports


def fix_unused_and_missing_imports(codeblock,
                                   add_missing=True,
                                   remove_unused="AUTOMATIC",
                                   add_mandatory=True,
                                   db=None,
                                   params=None):
    r"""
    Using C{pyflakes}, check for unused and missing imports, and fix them
    automatically.

    Also formats imports.

    In the example below, C{m1} and C{m3} are unused, so are automatically
    removed.  C{np} was undefined, so an C{import numpy as np} was
    automatically added.

      >>> codeblock = PythonBlock(
      ...     'from foo import m1, m2, m3, m4\n'
      ...     'm2, m4, np.foo', filename="/tmp/foo.py")

      >>> print fix_unused_and_missing_imports(codeblock, add_mandatory=False)
      [PYFLYBY] /tmp/foo.py: removed unused 'from foo import m1'
      [PYFLYBY] /tmp/foo.py: removed unused 'from foo import m3'
      [PYFLYBY] /tmp/foo.py: added 'import numpy as np'
      import numpy as np
      from foo import m2, m4
      m2, m4, np.foo

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      L{PythonBlock}
    """
    codeblock = PythonBlock(codeblock)
    if remove_unused == "AUTOMATIC":
        fn = codeblock.filename
        remove_unused = not (fn and
                             (fn.base == "__init__.py"
                              or ".pyflyby" in str(fn).split("/")))
    elif remove_unused is True or remove_unused is False:
        pass
    else:
        raise ValueError("Invalid remove_unused=%r" % (remove_unused,))
    params = ImportFormatParams(params)
    db = ImportDB.interpret_arg(db, target_filename=codeblock.filename)
    # Do a first pass reformatting the imports to get rid of repeated or
    # shadowed imports.  This is a kludge to deal with pyflakes complaining
    # about L1 here:
    #   import foo  # L1
    #   import foo  # L2
    #   foo         # L3
    # TODO: use our own AST parser which will have many benefits including
    # avoiding this kludge.
    codeblock = reformat_import_statements(codeblock, params=params)

    filename = codeblock.filename
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
        unused_imports.sort(key=lambda k: (k[1], k[0]))
        for import_as, lineno in unused_imports:
            try:
                imp = transformer.remove_import(import_as, lineno)
            except NoSuchImportError:
                logger.error(
                    "%s: couldn't remove import %r", filename, import_as,)
            except LineNumberNotFoundError as e:
                logger.error(
                    "%s: unused import %r on line %d not global",
                    filename, import_as, e.args[0])
            else:
                logger.info("%s: removed unused '%s'", filename, imp)

    if add_missing and missing_imports:
        missing_imports.sort(key=lambda k: (k[1], k[0]))
        known = db.known_imports.by_import_as
        # Decide on where to put each import to be added.  Find the import
        # block with the longest common prefix.  Tie-break by preferring later
        # blocks.
        added_imports = set()
        for import_as, lineno in missing_imports:
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

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      L{PythonBlock}
    """
    codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    filename = codeblock.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        broken = []
        for imp in list(block.importset.imports):
            ns = {}
            try:
                exec_(imp.pretty_print(), ns)
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

    Note that this requires involves actually importing C{foo.bar}, which may
    have side effects.  (TODO: rewrite to avoid this?)

    The result includes all imports from the C{email} module.  The result
    excludes shadowed imports.  In this example:
      1. The original C{MIMEAudio} import is shadowed, so it is removed.
      2. The C{MIMEImage} import in the C{email} module is shadowed by a
         subsequent import, so it is omitted.

      >>> codeblock = PythonBlock('from keyword import *', filename="/tmp/x.py")

      >>> print replace_star_imports(codeblock)
      [PYFLYBY] /tmp/x.py: replaced 'from keyword import *' with 2 imports
      from keyword import iskeyword, kwlist
      <BLANKLINE>

    Usually you'll want to remove unused imports after replacing star imports.

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      L{PythonBlock}
    """
    from pyflyby._modules import ModuleHandle
    params = ImportFormatParams(params)
    codeblock = PythonBlock(codeblock)
    filename = codeblock.filename
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    for block in transformer.import_blocks:
        # Iterate over the import statements in C{block.input}.  We do this
        # instead of using C{block.importset} because the latter doesn't
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
                    logger.warning("%s: found nothing to import from %s, ",
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
    Transform imports as specified by C{transformations}.

    transform_imports() perfectly replaces all imports in top-level import
    blocks.

    For the rest of the code body, transform_imports() does a crude textual
    string replacement.  This is imperfect but handles most cases.  There may
    be some false positives, but this is difficult to avoid.  Generally we do
    want to do replacements even within in strings and comments.

      >>> result = transform_imports("from m import x", {"m.x": "m.y.z"})
      >>> print result.text.joined.strip()
      from m.y import z as x

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @type transformations:
      C{dict} from C{str} to C{str}
    @param transformations:
      A map of import prefixes to replace, e.g. {"aa.bb": "xx.yy"}
    @rtype:
      L{PythonBlock}
    """
    codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    transformer = SourceToSourceFileImportsTransformation(codeblock)
    @memoize
    def transform_import(imp):
        # Transform a block of imports.
        # TODO: optimize
        # TODO: handle transformations containing both a.b=>x and a.b.c=>y
        for k, v in transformations.iteritems():
            imp = imp.replace(k, v)
        return imp
    def transform_block(block):
        # Do a crude string replacement in the PythonBlock.
        block = PythonBlock(block)
        s = block.text.joined
        for k, v in transformations.iteritems():
            s = re.sub("\\b%s\\b" % (re.escape(k)), v, s)
        return PythonBlock(s, flags=block.flags)
    # Loop over transformer blocks.
    for block in transformer.blocks:
        if isinstance(block, SourceToSourceImportBlockTransformation):
            input_imports = block.importset.imports
            output_imports = [ transform_import(imp) for imp in input_imports ]
            block.importset = ImportSet(output_imports, ignore_shadowed=True)
        else:
            block.output = transform_block(block.input)
    return transformer.output(params=params)


def canonicalize_imports(codeblock, params=None, db=None):
    """
    Transform C{codeblock} as specified by C{__canonical_imports__} in the
    global import library.

    @type codeblock:
      L{PythonBlock} or convertible (C{str})
    @rtype:
      L{PythonBlock}
    """
    codeblock = PythonBlock(codeblock)
    params = ImportFormatParams(params)
    db = ImportDB.interpret_arg(db, target_filename=codeblock.filename)
    transformations = db.canonical_imports
    return transform_imports(codeblock, transformations, params=params)
