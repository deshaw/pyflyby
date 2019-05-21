# pyflyby/test_docxref.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import (absolute_import, division, print_function,
                        with_statement)

from   .                        import xrefs

import pytest
from   six                      import PY3

if PY3:
    pytestmark = pytest.mark.skip("Epydoc does not support Python 3")

def test_find_bad_doc_cross_references_1():
    from   pyflyby._docxref         import find_bad_doc_cross_references
    from   pyflyby._modules         import ModuleHandle

    result = find_bad_doc_cross_references([xrefs])
    expected = (
        (ModuleHandle('tests.xrefs'), (3,), 'tests.xrefs', u'undefined_xref_from_module'),
        (ModuleHandle('tests.xrefs'), (19,), 'tests.xrefs.FooClass', u'undefined_xref_from_class'),
        # TODO: undefined_xref_from_class_attribute
        (ModuleHandle('tests.xrefs'), (31,), 'tests.xrefs.FooClass.foo_method', u'undefined_xref_from_method'),
        (ModuleHandle('tests.xrefs'), (38,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_wrapped_method'),
        (ModuleHandle('tests.xrefs'), (41,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_param'),
        (ModuleHandle('tests.xrefs'), (43,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_type'),
        (ModuleHandle('tests.xrefs'), (45,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_args_param'),
        (ModuleHandle('tests.xrefs'), (47,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_args_type'),
        (ModuleHandle('tests.xrefs'), (49,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_kwargs_param'),
        (ModuleHandle('tests.xrefs'), (51,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_kwargs_type'),
        (ModuleHandle('tests.xrefs'), (53,), 'tests.xrefs.FooClass.foo_wrapped_method', u'undefined_xref_from_rtype'),
        (ModuleHandle('tests.xrefs'), (61, 64), 'tests.xrefs.FooClass.foo_property', u'undefined_xref_from_property'),
        (ModuleHandle('tests.xrefs'), (64,), '??.foo_property', u'undefined_xref_from_property_rtype'),
        (ModuleHandle('tests.xrefs'), (71,), 'tests.xrefs.FooClass.__foo_private_method', u'undefined_xref_from_private_method'),
        (ModuleHandle('tests.xrefs'), (77,), 'tests.xrefs.foo_global_function', u'undefined_xref_from_global_function'),
    )
    assert result == expected
