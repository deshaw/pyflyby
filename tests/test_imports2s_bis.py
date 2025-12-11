from __future__ import print_function

import pytest
from   textwrap                 import dedent

from   pyflyby._importdb        import ImportDB
from   pyflyby._imports2s       import fix_unused_and_missing_imports
from   pyflyby._parse           import PythonBlock


@pytest.mark.parametrize(
    ("input_str", "expected_str"),
    [
        pytest.param(
            """\
import os  --::removed::--

def foo():
    import os
    import sys  --::removed::--
    return os.getenv('FOO')
""",
            """\
def foo():
    import os
    return os.getenv('FOO')
""",
            id="local_function_unused",
        ),
        pytest.param(
            """\
def foo():
    import sys
    return sys.version
""",
            """\
def foo():
    import sys
    return sys.version
""",
            id="local_function_used",
        ),
        pytest.param(
            """\
class MyClass:
    def method(self):
        import unused_mod  --::removed::--
        return 42
""",
            """\
class MyClass:
    def method(self):
        return 42
""",
            id="local_class_method",
        ),
        pytest.param(
            """\
def outer():
    def inner():
        import unused  --::removed::--
        return 1
    return inner()
""",
            """\
def outer():
    def inner():
        return 1
    return inner()
""",
            id="local_nested_function",
        ),
        pytest.param(
            """\
import os  # Global import  --::removed::--

def foo():
    import os # Local import shadows global
    return os.getenv('FOO')  # Uses local os
""",
            """\
def foo():
    import os # Local import shadows global
    return os.getenv('FOO')  # Uses local os
""",
            id="remove_shadowed_global",
        ),
    ],
)
def test_fix_unused_imports_local_scopes(input_str, expected_str):
    """Test unused import removal in various local scopes."""
    output = _apply_fix_unused_and_missing_imports(input_str)
    expected = _clean_code(expected_str)
    assert output == expected


@pytest.mark.parametrize(
    ("input_code", "expected_code"),
    [
        pytest.param(
            """\
import sys  # Global import

print(sys.version)  # Used at global scope

def foo():
    import sys  # Local import
    return sys.platform
""",
            """\
import sys # Global import

print(sys.version)  # Used at global scope

def foo():
    import sys  # Local import
    return sys.platform
""",
            id="keep_global_used_at_global",
        ),
        pytest.param(
            """\
import os  # Global import

def foo():
    import os  # Local import shadows global
    return os.path.join('a', 'b')

def bar():
    return os.getcwd()  # Uses global (no local import here)
""",
            """\
import os # Global import

def foo():
    import os  # Local import shadows global
    return os.path.join('a', 'b')

def bar():
    return os.getcwd()  # Uses global (no local import here)
""",
            id="keep_global_used_elsewhere",
        ),
    ],
)
def test_fix_unused_imports_keep_global(input_code, expected_code):
    """Keep global import when it's used in different scopes."""
    output = _apply_fix_unused_and_missing_imports(input_code)
    expected = _clean_code(expected_code)
    assert output == expected


def _clean_code(code: str) -> str:
    """Remove lines ending with --::removed::-- from code."""
    lines = code.split('\n')
    cleaned = [line for line in lines if not line.rstrip().endswith('--::removed::--')]
    return '\n'.join(cleaned)


def _apply_fix_unused_and_missing_imports(code: str) -> str:
    """Apply fix_unused_and_missing_imports to code and return result as string.

    The input code can use --::removed::-- markers at the end of lines to document
    which lines are expected to be removed. These markers are stripped before processing.
    """
    cleaned_code = _clean_code(code)
    input_block = PythonBlock(dedent(cleaned_code).lstrip())
    db = ImportDB("")
    output = fix_unused_and_missing_imports(input_block, db=db)
    return str(output)


# TODO: Implement removal of local import when global import is used elsewhere.
@pytest.mark.xfail(strict=False)
def test_fix_unused_imports_local_and_global_same_name():
    """Remove local import when global import is used elsewhere and sufficient."""
    input_str = """\
import os  # Global import

def fun_1():
    import os  # Local import - should be removed, global is sufficient --::removed::--
    return os.path.join('a', 'b')

def fun_2():
    return os.getcwd()  # Uses global import

result = os.getcwd()  # Global scope usage
"""

    expected_str = """\
import os  # Global import

def fun_1():
    return os.path.join('a', 'b')

def fun_2():
    return os.getcwd()  # Uses global import

result = os.getcwd()  # Global scope usage
"""

    output = _apply_fix_unused_and_missing_imports(input_str)
    expected = _clean_code(expected_str)
    assert output == expected


@pytest.mark.parametrize(
    "line,import_str,expected",
    [
        # Simple imports with variable spacing
        ("import os", "import os", True),
        ("import    os", "import os", True),
        ("  import os  ", "import os", True),
        ("import os", "import sys", False),
        # from...import statements
        ("from os import path", "from os import path", True),
        ("from    os    import    path", "from os import path", True),
        ("from os import path", "from sys import path", False),
        ("from os import path", "from os import sep", False),
        # Aliased imports
        ("import os as operating_system", "import os as operating_system", True),
        ("from os import path as p", "from os import path as p", True),
        ("from os import path   as   p", "from os import path as p", True),
        # Multiple imports on one line
        ("import os, sys", "import os", True),
        ("import os, sys", "import sys", True),
        ("import os, sys", "import json", False),
        # Edge cases
        ("# import os", "import os", False),
        ("", "import os", False),
        ("   ", "import os", False),
        ("x = import os", "import os", False),
    ],
    ids=[
        "simple_single_space",
        "simple_multiple_spaces",
        "simple_with_whitespace",
        "simple_non_matching",
        "from_single_space",
        "from_multiple_spaces",
        "from_non_matching_module",
        "from_non_matching_name",
        "alias_import",
        "alias_from_import",
        "alias_multiple_spaces",
        "multiple_on_line_first",
        "multiple_on_line_second",
        "multiple_on_line_non_matching",
        "edge_case_comment",
        "edge_case_empty",
        "edge_case_whitespace_only",
        "edge_case_non_import",
    ],
)
def test_line_contains_import(line, import_str, expected):
    """Test _line_contains_import with various import styles and spacing."""
    from pyflyby._imports2s import SourceToSourceFileImportsTransformation
    from pyflyby._importstmt import Import

    transformer = SourceToSourceFileImportsTransformation("import sys\n")
    imp = Import(import_str)
    assert transformer._line_contains_import(line, imp) == expected
