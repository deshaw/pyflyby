# pyflyby/_docxref.py.

# Module for checking Epydoc cross-references.

# Portions of the code below are derived from Epydoc, which is distributed
# under the MIT license:
#
#   Permission is hereby granted, free of charge, to any person obtaining a
#   copy of this software and any associated documentation files (the
#   "Software"), to deal in the Software without restriction, including
#   without limitation the rights to use, copy, modify, merge, publish,
#   distribute, sublicense, and/or sell copies of the Software, and to permit
#   persons to whom the Software is furnished to do so, subject to the
#   following conditions:
#
#   The above copyright notice and this permission notice shall be included in
#   all copies or substantial portions of the Software.
#
#   The software is provided "as is", without warranty of any kind, express or
#   implied, including but not limited to the warranties of merchantability,
#   fitness for a particular purpose and noninfringement. In no event shall
#   the authors or copyright holders be liable for any claim, damages or other
#   liability, whether in an action of contract, tort or otherwise, arising
#   from, out of or in connection with the software or the use or other
#   dealings in the software.

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import re
import six
from   six.moves                import builtins
from   textwrap                 import dedent

from   epydoc.apidoc            import (ClassDoc, ModuleDoc, PropertyDoc,
                                        RoutineDoc, UNKNOWN, VariableDoc)
from   epydoc.docbuilder        import build_doc_index
from   epydoc.markup.plaintext  import ParsedPlaintextDocstring

from   pyflyby._file            import Filename
from   pyflyby._idents          import DottedIdentifier
from   pyflyby._log             import logger
from   pyflyby._modules         import ModuleHandle
from   pyflyby._util            import cached_attribute, memoize, prefixes

# If someone references numpy.*, just assume it's OK - it's not worth
# following into numpy because it's too slow.
ASSUME_MODULES_OK = set(['numpy'])

@memoize
def map_strings_to_line_numbers(module):
    """
    Walk ``module.ast``, looking at all string literals.  Return a map from
    string literals to line numbers (1-index).

    :rtype:
      ``dict`` from ``str`` to (``int``, ``str``)
    """
    d = {}
    for field in module.block.string_literals():
        # Dedent because epydoc dedents strings and we need to look up by
        # those.  But keep track of original version because we need to count
        # exact line numbers.
        s = dedent(field.s).strip()
        start_lineno = field.startpos.lineno
        d[s] = (start_lineno, field.s)
    return d


def get_string_linenos(module, searchstring, within_string):
    """
    Return the line numbers (1-indexed) within ``filename`` that contain
    ``searchstring``.  Only consider string literals (i.e. not comments).
    First look for exact matches of ``within_string`` (modulo indenting) and
    then search within that.  Only if the ``within_string`` is not found,
    search the entire file.

    [If there's a comment on the same line as a string that also contains the
    searchstring, we'll get confused.]
    """
    module = ModuleHandle(module)
    regexp = re.compile(searchstring)
    map = map_strings_to_line_numbers(module)
    results = []
    def scan_within_string(results, start_lineno, orig_full_string):
        for i, line in enumerate(orig_full_string.splitlines()):
            if regexp.search(line):
                results.append( start_lineno + i )
    try:
        lineno, orig_full_string = map[within_string.strip()]
    except KeyError:
        pass
    else:
        # We found the larger string exactly within the ast.
        scan_within_string(results, lineno, orig_full_string)
        if results:
            return tuple(results)
        # We could continue down if this ever happened.
        raise Exception(
            "Found superstring in %r but not substring %r within superstring"
            % (module.filename, searchstring))
    # Try a full text search.
    for lineno, orig_full_string in map.values():
        scan_within_string(results, lineno, orig_full_string)
    if results:
        return tuple(sorted(results))
    raise Exception(
        "Could not find %r anywhere in %r" % (searchstring, module.filename))


def describe_xref(identifier, container):
    module = ModuleHandle(str(container.defining_module.canonical_name))
    assert module.filename == Filename(container.defining_module.filename)
    linenos = get_string_linenos(
        module,
        "(L{|<)%s" % (identifier,),
        container.docstring)
    return (module, linenos, str(container.canonical_name), identifier)



def safe_build_doc_index(modules):
    # build_doc_index isn't re-entrant due to crappy caching! >:(
    from epydoc.docintrospecter import clear_cache
    clear_cache()
    from epydoc.docparser import _moduledoc_cache
    _moduledoc_cache.clear()
    # Build a new DocIndex.  It swallows exceptions and returns None on error!
    # >:(
    result = build_doc_index(modules)
    if result is None:
        raise Exception("Failed to build doc index on %r" % (modules,))
    return result


class ExpandedDocIndex(object):
    """
    A wrapper around DocIndex that automatically expands with more modules as
    needed.
    """
    # TODO: this is kludgy and inefficient since it re-reads modules.
    def __init__(self, modules):
        self.modules = set([ModuleHandle(m) for m in modules])

    def add_module(self, module):
        """
        Adds ``module`` and recreates the DocIndex with the updated set of
        modules.

        :return:
          Whether anything was added.
        """
        module = ModuleHandle(module)
        for prefix in module.ancestors:
            if prefix in self.modules:
                # The module, or a prefix of it, was already added.
                return False

        for existing_module in sorted(self.modules):
            if existing_module.startswith(module):
                # This supersedes an existing module.
                assert existing_module != module
                self.modules.remove(existing_module)

        logger.debug("Expanding docindex to include %r", module)
        self.modules.add(module)
        del self.docindex
        return True

    def find(self, a, b):
        return self.docindex.find(a, b)

    def get_vardoc(self, a):
        return self.docindex.get_vardoc(a)

    @cached_attribute
    def docindex(self):
        return safe_build_doc_index(
            [str(m.name) for m in sorted(self.modules)])


def remove_epydoc_sym_suffix(s):
    """
    Remove trailing "'" that Epydoc annoyingly adds to 'shadowed' names.

      >>> remove_epydoc_sym_suffix("a.b'.c'.d")
      'a.b.c.d'

    """
    return re.sub(r"'([.]|$)", r'\1', s)

class XrefScanner(object):

    def __init__(self, modules):
        self.modules = modules
        self.docindex = safe_build_doc_index(modules)

    @cached_attribute
    def expanded_docindex(self):
        return ExpandedDocIndex(self.modules)

    def scan(self):
        self._failed_xrefs = []
        valdocs = sorted(self.docindex.reachable_valdocs(
            imports=False, packages=False, bases=False, submodules=False,
            subclasses=False, private=True
            ))
        for doc in valdocs:
            if isinstance(doc, ClassDoc):
                self.scan_class(doc)
            elif isinstance(doc, ModuleDoc):
                self.scan_module(doc)
        return tuple(sorted(self._failed_xrefs))

    def scan_module(self, doc):
        self.descr(doc)
        if doc.is_package is True:
            for submodule in doc.submodules:
                self.scan_module(submodule)
            # self.scan_module_list(doc)
        self.scan_details_list(doc, "function")
        self.scan_details_list(doc, "other")

    def scan_class(self, doc):
        self.descr(doc)
        self.scan_details_list(doc, "method")
        self.scan_details_list(doc, "classvariable")
        self.scan_details_list(doc, "instancevariable")
        self.scan_details_list(doc, "property")

    def scan_details_list(self, doc, value_type):
        detailed = True
        if isinstance(doc, ClassDoc):
            var_docs = doc.select_variables(value_type=value_type,
                                            imported=False, inherited=False,
                                            public=None,
                                            detailed=detailed)
        else:
            var_docs = doc.select_variables(value_type=value_type,
                                            imported=False,
                                            public=None,
                                            detailed=detailed)
        for var_doc in var_docs:
            self.scan_details(var_doc)

    def scan_details(self, var_doc):
        self.descr(var_doc)
        if isinstance(var_doc.value, RoutineDoc):
            self.return_type(var_doc)
            self.return_descr(var_doc)
            for (arg_names, arg_descr) in var_doc.value.arg_descrs:
                self.scan_docstring(arg_descr, var_doc.value)
            for arg in var_doc.value.arg_types:
                self.scan_docstring(
                    var_doc.value.arg_types[arg], var_doc.value)
        elif isinstance(var_doc.value, PropertyDoc):
            prop_doc = var_doc.value
            self.return_type(prop_doc.fget)
            self.return_type(prop_doc.fset)
            self.return_type(prop_doc.fdel)
        else:
            self.type_descr(var_doc)

    def _scan_attr(self, attr, api_doc):
        if api_doc in (None, UNKNOWN):
            return ''
        pds = getattr(api_doc, attr, None) # pds = ParsedDocstring.
        if pds not in (None, UNKNOWN):
            self.scan_docstring(pds, api_doc)
        elif isinstance(api_doc, VariableDoc):
            self._scan_attr(attr, api_doc.value)

    def summary(self, api_doc):
        self._scan_attr('summary', api_doc)

    def descr(self, api_doc):
        self._scan_attr('descr', api_doc)

    def type_descr(self, api_doc):
        self._scan_attr('type_descr', api_doc)

    def return_type(self, api_doc):
        self._scan_attr('return_type', api_doc)

    def return_descr(self, api_doc):
        self._scan_attr('return_descr', api_doc)

    def check_xref(self, identifier, container):
        """
        Check that ``identifier`` cross-references a proper symbol.

        Look in modules that we weren't explicitly asked to look in, if
        needed.
        """
        if identifier in builtins.__dict__:
            return True
        def check_container():
            if self.expanded_docindex.find(identifier, container) is not None:
                return True
            if isinstance(container, RoutineDoc):
                tcontainer = self.expanded_docindex.get_vardoc(
                    container.canonical_name)
                doc = self.expanded_docindex.find(identifier, tcontainer)
                while (doc is not None and tcontainer not in (None, UNKNOWN)
                       and tcontainer.overrides not in (None, UNKNOWN)):
                    tcontainer = tcontainer.overrides
                    doc = self.expanded_docindex.find(identifier, tcontainer)
                return doc is not None
            return False
        def check_defining_module(x):
            if x is None:
                return False
            defining_module_name = remove_epydoc_sym_suffix(str(
                x.defining_module.canonical_name))
            if defining_module_name in ASSUME_MODULES_OK:
                return True
            if self.expanded_docindex.add_module(defining_module_name):
                if check_container():
                    return True
            return False
        if check_container():
            return True
        if (isinstance(container, RoutineDoc) and
            identifier in container.all_args()):
            return True
        if check_defining_module(container):
            return True
        # If the user has imported foo.bar.baz as baz and now uses
        # ``baz.quux``, we need to add the module foo.bar.baz.
        for prefix in reversed(list(prefixes(
                    DottedIdentifier(remove_epydoc_sym_suffix(identifier))))):
            if check_defining_module(
                self.docindex.find(str(prefix), container)):
                return True
        try:
            module = ModuleHandle.containing(identifier)
        except ImportError:
            pass
        else:
            if str(module.name) in ASSUME_MODULES_OK:
                return True
            if self.expanded_docindex.add_module(module):
                if check_container():
                    return True
        return False

    def scan_docstring(self, parsed_docstring, container):
        if parsed_docstring in (None, UNKNOWN): return ''
        if isinstance(parsed_docstring, ParsedPlaintextDocstring):
            return ''

        def scan_tree(tree):
            if isinstance(tree, six.string_types):
                return tree
            variables = [scan_tree(child) for child in tree.children]
            if tree.tag == 'link':
                identifier = variables[1]
                if not self.check_xref(identifier, container):
                    self._failed_xrefs.append(
                        describe_xref(identifier, container) )
                return '?'
            elif tree.tag == 'indexed':
                return '?'
            elif tree.tag in ('epytext', 'section', 'tag', 'arg',
                              'name', 'target', 'html', 'para'):
                return ''.join(variables)
            return '?'

        scan_tree(parsed_docstring._tree)


def find_bad_doc_cross_references(names):
    """
    Find docstring cross references that fail to resolve.

    :type names:
      Sequence of module names or filenames.
    :return:
      Sequence of ``(module, linenos, container_name, identifier)`` tuples.
    """
    xrs = XrefScanner(names)
    return xrs.scan()
