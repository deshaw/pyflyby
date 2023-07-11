"""
Blah.
L{undefined_xref_from_module}

"""

# pyflyby/tests/xrefs.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/




class FooClass(object):
    """
    Blah.
    L{undefined_xref_from_class}
    """

    foo_attribute = 123
    """
    Blah.
    L{undefined_xref_from_class_attribute}
    """

    def foo_method(self):
        """
        Blah.
        L{undefined_xref_from_method}
        """

    @staticmethod
    def foo_wrapped_method(abc, *args, **kwargs):
        """
        Blah.
        L{undefined_xref_from_wrapped_method}

        @param abc:
          L{undefined_xref_from_param}
        @type abc:
          L{undefined_xref_from_type}
        @param args:
          L{undefined_xref_from_args_param}
        @type args:
          L{undefined_xref_from_args_type}
        @param kwargs:
          L{undefined_xref_from_kwargs_param}
        @type kwargs:
          L{undefined_xref_from_kwargs_type}
        @rtype:
          L{undefined_xref_from_rtype}
        """

    @property
    def foo_property(self):
        """
        Blah.

        L{undefined_xref_from_property}

        @rtype:
          L{undefined_xref_from_property_rtype}
        """

    def __foo_private_method(self):
        """
        Blah.

        L{undefined_xref_from_private_method}
        """

def foo_global_function():
    """
    Blah.
    L{undefined_xref_from_global_function}
    """

foo_module_attribute = 123
"""
Blah.
L{undefined_xref_from_module_attribute}
"""

foo_module_attribute_2 = 123
"""
Blah L{undefined_xref_from_module_attribute_first_paragraph}.
"""

foo_indexed = 123
"""
Blah.

L{undefined_xref_extern_a <dummy_module1.undefined_xref_extern_b>}
"""
