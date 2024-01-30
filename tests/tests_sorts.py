from   pyflyby._parse     import PythonBlock
from   pyflyby._imports2s import sort_imports
from textwrap import dedent
import pytest

code1 = dedent("""
        import external
        import os
        import sympy
        import numpy
        import json
        import simplejson

        from pkg1.mod1 import foo
        from pkg1.mod2 import bar
        from pkg2 import baz
        import yy

        from pkg1.mod1 import foo2
        from pkg1.mod3 import quux
        from pkg2 import baar
        import zz
    """)

# The logic requested in issue 13 whas to keep blocks, but order
# lexicographically. we do seem to be splitting stdlib from installed packages,
# but not adding a blank line and then sort lexicographically if an package has
# several submodules importted we put it in a block, otherwise we keep
# everything together.

expected1 = dedent("""
        import json
        import os
        import external
        import numpy

        from pkg1.mod1 import foo, foo2
        from pkg1.mod2 import bar
        from pkg1.mod3 import quux

        from pkg2 import baar, baz
        import simplejson
        import sympy
        import yy
        import zz
    """)

@pytest.mark.parametrize('code, expected',[(code1, expected1)])
def test_sort_1(code, expected):

    assert str(sort_imports(PythonBlock(code))) == expected
    # expected is stable
    assert str(sort_imports(PythonBlock(expected))) == expected

