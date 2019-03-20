# pyflyby/test_docxref.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

from   pyflyby._docxref         import find_bad_doc_cross_references
from   pyflyby._modules         import ModuleHandle

from   .                        import xrefs

def test_find_bad_doc_cross_references_1():
    result = find_bad_doc_cross_references([xrefs])
    expected = (
        (ModuleHandle('xrefs'), (3,), 'xrefs', u'undefined_xref_from_module'),
        (ModuleHandle('xrefs'), (18,), 'xrefs.FooClass', u'undefined_xref_from_class'),
        # TODO: undefined_xref_from_class_attribute
        (ModuleHandle('xrefs'), (30,), 'xrefs.FooClass.foo_method', u'undefined_xref_from_method'),
        (ModuleHandle('xrefs'), (37,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_wrapped_method'),
        (ModuleHandle('xrefs'), (40,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_param'),
        (ModuleHandle('xrefs'), (42,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_type'),
        (ModuleHandle('xrefs'), (44,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_args_param'),
        (ModuleHandle('xrefs'), (46,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_args_type'),
        (ModuleHandle('xrefs'), (48,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_kwargs_param'),
        (ModuleHandle('xrefs'), (50,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_kwargs_type'),
        (ModuleHandle('xrefs'), (52,), 'xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_rtype'),
        (ModuleHandle('xrefs'), (60, 63), 'xrefs.FooClass.foo_property', u'undefined_xref_from_property'),
        (ModuleHandle('xrefs'), (63,), '??.foo_property', u'undefined_xref_from_property_rtype'),
        (ModuleHandle('xrefs'), (70,), 'xrefs.FooClass.__foo_private_method', u'undefined_xref_from_private_method'),
        (ModuleHandle('xrefs'), (76,), 'xrefs.foo_global_function', u'undefined_xref_from_global_function'),
    )
    assert result == expected
