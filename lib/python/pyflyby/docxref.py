#!/usr/bin/env python

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

from __future__ import absolute_import, division, with_statement

import __builtin__
import ast
import re
from   textwrap                 import dedent
import types

from   epydoc.apidoc            import (ClassDoc, ModuleDoc, PropertyDoc,
                                        RoutineDoc, UNKNOWN, VariableDoc)
from   epydoc.docbuilder        import build_doc_index

from   pyflyby.log              import logger
from   pyflyby.util             import cached_attribute, memoize


def import_module(module_name):
    logger.debug("Importing %r", module_name)
    try:
        return __import__(module_name, fromlist=['dummy'])
    except Exception as e:
        logger.debug("Failed to import %r: %s: %r",
                     module_name, type(e).__name__, e)
        raise

def pyc_to_py(filename):
    if filename.endswith(".pyc"):
        filename = filename[:-1]
    return filename

@memoize
def filename_of_module(module_name):
    # This is inefficient (and potentially ugly exceptions) if the module
    # isn't already loaded, but in our use cases it already is.
    module = import_module(module_name)
    return pyc_to_py(module.__file__)

@memoize
def parse_module(filename):
    with open(filename) as f:
        filecontent = f.read()
    return ast.parse(filecontent, filename)

@memoize
def map_strings_to_line_numbers(ast_node):
    """
    Walk C{ast_node}, looking at all string literals.  Return a map from
    string literals to line numbers (1-index).

    @rtype:
      C{dict} from C{str} to (C{int}, C{str})
    """
    d = {}
    for node in ast.walk(ast_node):
        for fieldname, field in ast.iter_fields(node):
            if isinstance(field, ast.Str):
                if not hasattr(field, 'lineno'):
                    # Not a real string literal - it's something like
                    # ast._Index.
                    continue
                # Dedent because epydoc dedents strings and we need to look up
                # by those.  But keep track of original version because we
                # need to count exact line numbers.
                s = dedent(field.s).strip()
                start_lineno = field.lineno - len(field.s.splitlines()) + 1
                d[s] = (start_lineno, field.s)
    return d


def get_string_linenos_in_module(filename, searchstring, within_string):
    """
    Return the line numbers (1-indexed) within C{filename} that contain
    C{searchstring}.  Only consider string literals (i.e. not comments).
    First look for exact matches of C{within_string} (modulo indenting) and
    then search within that.  Only if the C{within_string} is not found,
    search the entire file.

    [If there's a comment on the same line as a string that also contains the
    searchstring, we'll get confused.]
    """
    regexp = re.compile(searchstring)
    map = map_strings_to_line_numbers(parse_module(filename))
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
            % (filename, searchstring))
    # Try a full text search.
    for lineno, orig_full_string in map.itervalues():
        scan_within_string(results, lineno, orig_full_string)
    if results:
        return tuple(sorted(results))
    raise Exception(
        "Could not find %r anywhere in %r" % (searchstring, filename))


def describe_xref(identifier, container):
    module_name = str(container.defining_module.canonical_name)
    filename = container.defining_module.filename
    assert filename == filename_of_module(module_name)
    linenos = get_string_linenos_in_module(
        filename,
        "(L{|<)%s" % (identifier,),
        container.docstring)
    return (module_name, filename, linenos, str(container.canonical_name),
            identifier)


def import_module_containing(identifier):
    """
    Try to find the module that defines a name such as C{a.b.c} by trying to
    import C{a}, C{a.b}, and C{a.b.c}.

    @return:
      The name of the 'deepest' module (most commonly it would be C{a.b} in
      this example).
    @rtype:
      C{str}
    """
    # In the code below we catch "Exception" rather than just ImportError or
    # AttributeError since importing and __getattr__ing can raise other
    # exceptions.
    parts = identifier.split('.')
    try:
        result = import_module(parts[0])
        module_name = parts[0]
    except Exception:
        return None
    for i, part in enumerate(parts[1:], 2):
        try:
            result = getattr(result, part)
        except Exception:
            try:
                module_name = '.'.join(parts[:i])
                result = import_module(module_name)
            except Exception:
                return None
        else:
            if isinstance(result, types.ModuleType):
                module_name = '.'.join(parts[:i])
    logger.debug("Imported %r to get %r", module_name, identifier)
    return module_name


def safe_build_doc_index(modules):
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
        self.modules = set(modules)

    def add_module(self, module_name):
        """
        Adds C{module} and recreates the DocIndex with the updated set of
        modules.

        @return:
          Whether anything was added.  If module_name is invalid or already
          added, quietly return False.
        """
        if not module_name:
            return False
        # Only add if it's importable.
        try:
            module = import_module(module_name)
        except Exception:
            return False
        if module_name in self.modules:
            return False
        # Also check by filename, in case the user originally specified
        # a filename rather than module name.
        filename = pyc_to_py(module.__file__)
        if filename in self.modules:
            return False
        logger.debug("Expanding docindex to include %r", module_name)
        self.modules.add(module_name)
        del self.docindex
        return True

    def find(self, a, b):
        return self.docindex.find(a, b)

    def get_vardoc(self, a):
        return self.docindex.get_vardoc(a)

    @cached_attribute
    def docindex(self):
        return safe_build_doc_index(sorted(self.modules))


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
        Check that C{identifier} cross-references a proper symbol.

        Look in modules that we weren't explicitly asked to look in, if
        needed.
        """
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
        if check_container():
            return True
        if (isinstance(container, RoutineDoc) and
            identifier in container.all_args()):
            return '?'
        if self.expanded_docindex.add_module(
            str(container.defining_module.canonical_name)):
            if check_container():
                return True
        if identifier in __builtin__.__dict__:
            return True
        if self.expanded_docindex.add_module(
            import_module_containing(identifier)):
            if check_container():
                return True
        return False

    def scan_docstring(self, parsed_docstring, container):
        if parsed_docstring in (None, UNKNOWN): return ''

        def scan_tree(tree):
            if isinstance(tree, basestring):
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

    @type names:
      Sequence of module names or filenames.
    @rtype:
      Sequence of C{(module_name, filename, linenos, container_name,
      identifier)} tuples.
    """
    xrs = XrefScanner(names)
    return xrs.scan()
