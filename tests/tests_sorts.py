from   lib.python.pyflyby._importstmt \
                                import ImportFormatParams
from   pyflyby._import_sorting  import sort_imports
from   pyflyby._imports2s       import fix_unused_and_missing_imports
from   pyflyby._parse           import PythonBlock
import pytest
from   textwrap                 import dedent

code1 = dedent("""
        import external
        import os
        import sympy
        import numpy
        import json
        import simplejson

        from pkg2 import same, line
        from pkg1.mod1 import foo
        from pkg1.mod2 import bar
        from pkg2 import baz
        import yy

        from pkg1.mod1 import foo2
        from pkg1.mod3 import quux
        from pkg2 import baar
        import zz
    """).strip()

# The logic requested in issue 13 was to keep blocks, but order
# lexicographically. we do seem to be splitting stdlib from installed packages,
# but not adding a blank line and then sort lexicographically if an package has
# several submodules imported we put it in a block, otherwise we keep
# everything together.

# note that sorting does not concatenate same imports together, but cannonicalize
# in tidy import will.

expected1 = dedent("""
        import external
        import json
        import numpy
        import os

        from pkg1.mod1                import foo
        from pkg1.mod1                import foo2
        from pkg1.mod2                import bar
        from pkg1.mod3                import quux

        from pkg2                     import same, line
        from pkg2                     import baz
        from pkg2                     import baar

        import simplejson
        import sympy
        import yy
        import zz
    """).strip()+'\n\n'


code2 = dedent(
    """
    '''module docstring'''
    import os

    pass
    """
).strip()

expected2 = code2


code3 = dedent("""
    import os

    if True:
        "ok"
    """).strip()

expected3 = code3

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


code4 = dedent(
    """
from __future__ import print_function

from pyflyby._cmdline         import filename_args, hfmt, parse_args
from pyflyby._importclns      import ImportSet
from pyflyby._importdb        import ImportDB

import re
import sys

def main():
    def addopts(parser):
        pass"""
).strip()

expected4 = code4


@pytest.mark.parametrize(
    "code, expected",
    [(code1, expected1), (code2, expected2), (code3, expected3), (code4, expected4)],
)
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
