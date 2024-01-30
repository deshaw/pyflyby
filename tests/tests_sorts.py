from pyflyby._parse import PythonBlock
from pyflyby._imports2s import sort_imports, fix_unused_and_missing_imports
from textwrap import dedent
from lib.python.pyflyby._importstmt import ImportFormatParams
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

# stable should not change
stable_1 = dedent(
    """
        #!/usr/local/bin/python3

        from   deshaw.abc               import DAYS
        from   deshaw.py                import tuple

        print(DAYS.days(20240101, 20241231))
        print(tuple("hello"))
    """
)


@pytest.mark.parametrize("code, expected", [(code1, expected1)])
def test_sort_1(code, expected):

    assert str(sort_imports(PythonBlock(code))) == expected
    # expected is stable
    assert str(sort_imports(PythonBlock(expected))) == expected


@pytest.mark.parametrize("code", [stable_1])
def test_stable(code):
    params = ImportFormatParams(
        align_imports=(32,),
        from_spaces=3,
        separate_from_imports=False,
        max_line_length=None,
        use_black=False,
        align_future=False,
        hanging_indent="never",
    )
    add_missing = False
    remove_unused = False
    add_mandatory = False

    result = fix_unused_and_missing_imports(
        PythonBlock(code),
        params=params,
        add_missing=add_missing,
        remove_unused=remove_unused,
        add_mandatory=add_mandatory,
    )

    assert str(result) == str(stable_1)
