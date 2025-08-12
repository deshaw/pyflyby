# pyflyby/test_importstmt.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/


import pytest
from   pytest                   import raises
from   unittest.mock            import patch

from   pyflyby._flags           import CompilerFlags
from   pyflyby._format          import FormatParams
from   pyflyby._importstmt      import (Import, ImportSplit, ImportStatement,
                                        read_black_config)

def test_Import_from_parts_1():
    imp = Import.from_parts(".foo.bar", "bar")
    assert imp.fullname  == ".foo.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit(".foo", "bar", None)
    assert str(imp)      == "from .foo import bar"


def test_Import_from_split_1():
    imp = Import(ImportSplit(".foo", "bar", None))
    assert imp.fullname  == ".foo.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit(".foo", "bar", None)
    assert str(imp)      == "from .foo import bar"


def test_Import_from_Statement_1():
    imp = Import(ImportStatement("from foo import bar"))
    assert imp.fullname  == "foo.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit("foo", "bar", None)
    assert str(imp)      == "from foo import bar"
    assert imp == Import("from foo import bar")


def test_Import_basic_1():
    imp = Import("from foo.foof import bar")
    assert imp.fullname  == "foo.foof.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit("foo.foof", "bar", None)
    assert str(imp)      == "from foo.foof import bar"


def test_Import_relative_1():
    imp = Import("from .foo import bar")
    assert imp.fullname  == ".foo.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit(".foo", "bar", None)
    assert str(imp)      == "from .foo import bar"


def test_Import_relative_local_1():
    imp = Import("from . import foo")
    assert imp.fullname  == ".foo"
    assert imp.import_as == "foo"
    assert imp.split     == ImportSplit(".", "foo", None)
    assert str(imp)      == "from . import foo"


def test_Import_module_1():
    imp = Import("import   foo . bar")
    assert imp.fullname  == "foo.bar"
    assert imp.import_as == "foo.bar"
    assert imp.split     == ImportSplit(None, "foo.bar", None)
    assert str(imp)      == "import foo.bar"


def test_Import_import_as_1():
    imp = Import("import   foo . bar  as  baz")
    assert imp.fullname  == "foo.bar"
    assert imp.import_as == "baz"
    assert imp.split     == ImportSplit("foo", "bar", "baz")
    assert str(imp)      == "from foo import bar as baz"


def test_Import_import_as_same_1():
    imp = Import("import   foo . bar  as  bar")
    assert imp.fullname  == "foo.bar"
    assert imp.import_as == "bar"
    assert imp.split     == ImportSplit("foo", "bar", None)
    assert str(imp)      == "from foo import bar"
    assert imp == Import("from foo import bar")


def test_Import_eqne_1():
    imp1a = Import("from foo import bar")
    imp1b = Import("from foo import bar")
    imp2  = Import("from .foo import bar")
    assert     (imp1a == imp1b)
    assert not (imp1a != imp1b)
    assert     (imp1a != imp2 )
    assert not (imp1a == imp2 )


def test_Import_eqne_2():
    imp1a = Import("from foo import bar")
    imp1b = Import("from foo import bar")
    imp2  = Import("from foo import bar as Bar")
    assert     (imp1a == imp1b)
    assert not (imp1a != imp1b)
    assert     (imp1a != imp2 )
    assert not (imp1a == imp2 )


def test_Import_prefix_match_1():
    result = Import("import ab.cd.ef").prefix_match(Import("import ab.cd.xy"))
    assert result == ('ab', 'cd')


def test_Import_replace_1():
    result = Import("from aa.bb import cc").replace("aa.bb", "xx.yy")
    assert result == Import('from xx.yy import cc')


def test_Import_replace_2():
    result = Import("from aa import bb").replace("aa.bb", "xx.yy")
    assert result == Import('from xx import yy as bb')


@patch("pyflyby._importstmt.read_black_config", lambda: {"line_length": 20})
def test_Import_black_line_length():
    """Test that a black config takes precedence over the default line length."""
    stmt = Import("from a123456789 import b123456789")
    result = stmt.pretty_print(params=FormatParams(use_black=True))
    assert result == "from a123456789 import (\n    b123456789,\n)\n"


@patch("pyflyby._importstmt.read_black_config", lambda: {})
def test_Import_black_line_length2():
    """Test that the default line length is used if no black config is present."""
    stmt = Import("from math import sincostansinhcoshtanhlogfloorlog10remainderfactorialnextafter")
    result = stmt.pretty_print(params=FormatParams(use_black=True))
    assert result == "from math import sincostansinhcoshtanhlogfloorlog10remainderfactorialnextafter\n"

@patch("pyflyby._importstmt.read_black_config", lambda: {})
def test_Import_black_line_length3():
    """Test that the default line length is used if no black config is present."""
    stmt = Import("from math import sincostansinhcoshtanhlogfloorlog10remainderfactorialnextafterradians")
    result = stmt.pretty_print(params=FormatParams(use_black=True))
    assert result == "from math import (\n    sincostansinhcoshtanhlogfloorlog10remainderfactorialnextafterradians,\n)\n"

@patch("pyflyby._importstmt.read_black_config", lambda: {"line_length": 200})
def test_Import_black_line_length4():
    """Test that a command line --width takes precedence over a black config."""
    stmt = Import("from a123456789 import b123456789")
    result = stmt.pretty_print(params=FormatParams(use_black=True, max_line_length=20))
    assert result == "from a123456789 import (\n    b123456789,\n)\n"


def test_ImportStatement_1():
    stmt = ImportStatement("import  foo . bar")
    assert stmt.fromname == None
    assert stmt.aliases == (("foo.bar", None),)
    assert stmt.imports == (Import(ImportSplit(None, "foo.bar", None)),)
    assert str(stmt) == "import foo.bar"


def test_ImportStatement_member_1():
    stmt = ImportStatement("from  foo  import  bar ")
    assert stmt.fromname == "foo"
    assert stmt.aliases == (("bar", None),)
    assert stmt.imports == (Import(ImportSplit("foo", "bar", None)),)
    assert str(stmt) == "from foo import bar"


def test_ImportStatement_multi_1():
    stmt = ImportStatement("from foo  import bar, bar2, bar")
    assert stmt.fromname == "foo"
    assert stmt.aliases == (("bar", None), ("bar2", None), ("bar", None))
    assert stmt.imports == (Import(ImportSplit("foo", "bar", None)),
                            Import(ImportSplit("foo", "bar2", None)),
                            Import(ImportSplit("foo", "bar", None)))
    assert str(stmt) == "from foo import bar, bar2, bar"


def test_ImportStatement_alias_1():
    stmt = ImportStatement("from foo  import bar  as  bar,   bar as   baz")
    assert stmt.fromname == "foo"
    assert stmt.aliases == (("bar", "bar"), ("bar", "baz"))
    assert stmt.imports == (Import(ImportSplit("foo", "bar", "bar")),
                            Import(ImportSplit("foo", "bar", "baz")))
    assert str(stmt) == "from foo import bar as bar, bar as baz"


def test_ImportStatement_deep_member_1():
    stmt = ImportStatement("from foo.bar import baz")
    assert stmt.fromname == "foo.bar"
    assert stmt.aliases == (("baz", None),)
    assert stmt.imports == (Import(ImportSplit("foo.bar", "baz", None)),)
    assert str(stmt) == "from foo.bar import baz"


def test_ImportStatement_relative_1():
    stmt = ImportStatement("from .foo import bar")
    assert stmt.fromname == ".foo"
    assert stmt.aliases == (("bar", None),)
    assert stmt.imports == (Import(ImportSplit(".foo", "bar", None)),)
    assert str(stmt) == "from .foo import bar"


def test_ImportStatement_relative_local_1():
    stmt = ImportStatement("from .  import bar , bar2 as baz2")
    assert stmt.fromname == "."
    assert stmt.aliases == (("bar", None), ("bar2", "baz2"))
    assert stmt.imports == (Import(ImportSplit(".", "bar", None)),
                            Import(ImportSplit(".", "bar2", "baz2")))
    assert str(stmt) == "from . import bar, bar2 as baz2"


def test_ImportStatement_flags_1():
    stmt = ImportStatement("from __future__ import division, print_function")
    assert stmt.flags == CompilerFlags('division', 'print_function')


def test_ImportStatement_flags_2():
    stmt = ImportStatement("from _future__ import division, print_function")
    assert stmt.flags == CompilerFlags.from_int(0)


def test_ImportStatement_eqne_1():
    stmt1a = ImportStatement("from a import b"   )
    stmt1b = ImportStatement("from a import b"   )
    stmt2  = ImportStatement("from a import b, b")
    assert     (stmt1a == stmt1b)
    assert not (stmt1a != stmt1b)
    assert     (stmt1a != stmt2 )
    assert not (stmt1a == stmt2 )


def test_ImportStatement_eqne_2():
    stmt1a = ImportStatement("from a import b"   )
    stmt1b = ImportStatement("from a import b"   )
    stmt2  = ImportStatement("from a import b as b")
    assert     (stmt1a == stmt1b)
    assert not (stmt1a != stmt1b)
    assert     (stmt1a != stmt2 )
    assert not (stmt1a == stmt2 )


@patch("black.files.find_pyproject_toml", lambda root: None)
def test_ImportStatement_pretty_print_black_no_config():
    # running should not error out when no pyproject.toml file is found
    stmt = ImportStatement("from a import b")
    result = stmt.pretty_print(params=FormatParams(use_black=True))
    assert isinstance(result, str)


@patch("black.files.find_pyproject_toml", lambda root: None)
def test_read_black_config_no_config():
    # reading black config should work when no pyproject.toml file is found
    config = read_black_config()
    assert config == {}


@patch("black.files.find_pyproject_toml", lambda root: "pyproject.toml")
@patch(
    "black.files.parse_pyproject_toml",
    lambda path: {
        "line_length": 80,
        "skip_magic_trailing_comma": True,
        "skip_string_normalization": False,
        "skip_source_first_line": True
    }
)
def test_read_black_config_extracts_config_subset():
    config = read_black_config()
    # should copy the desired black options
    assert config["line_length"] == 80
    assert config["skip_magic_trailing_comma"] == True
    assert config["skip_string_normalization"] == False
    # should not copy anything else
    assert "skip_source_first_line" not in config


@patch("black.files.find_pyproject_toml", lambda root: "pyproject.toml")
@patch("black.files.parse_pyproject_toml", lambda path: {"target_version": ["py310", "py311"]})
def test_read_black_config_target_version_list():
    config = read_black_config()
    assert config["target_version"] == {"py310", "py311"}


@patch("black.files.find_pyproject_toml", lambda root: "pyproject.toml")
@patch("black.files.parse_pyproject_toml", lambda path: {"target_version": "py311"})
def test_read_black_config_target_version_str():
    config = read_black_config()
    assert config["target_version"] == "py311"

@patch("black.files.find_pyproject_toml", lambda root: "pyproject.toml")
@patch("black.files.parse_pyproject_toml", lambda path: {"target_version": object()})
def test_read_black_config_target_version_other():
    with raises(ValueError, match="Invalid config for black"):
        read_black_config()

@pytest.mark.parametrize(
    "comment",
    [
        None,
        "comment",
    ]
)
def test_Import_with_comments(comment):
    imp = Import.from_split(("foo", "bar", "baz"), comment=comment)
    assert imp.comment == comment


@pytest.mark.parametrize(
    ("text", "comment", "should_keep"),
    [
        ("import foo # test comment # more text", "test comment # more text", True),
        ("from foo import bar, bar2 # test comment", "test comment", False),
        ("from foo import bar, bar2, baz, quux, abc, defg, lmo, pqr, nmp, qrs, ghi, jkl # test comment", "test comment", False),
        ("from foo import (\n    bar # test comment\n)", "test comment", True),
        ("from foo import (\n\n    bar # test comment\n)", "test comment", True),
        ("from foo import ( # test comment\n    bar\n)", "test comment", True),
        ("from foo import ( # test comment\n    bar,\n)", "test comment", True),
        ("from foo import (\n    bar, # test comment\n)", "test comment", True),
        ("from foo import (\n    bar,\n) # test comment\n", "test comment", True),
        ("from foo import (\n    bar, # test comment\n    bar2\n)", "test comment", False),
        ("from foo import (\n    bar,\n    bar2 # test comment\n)", "test comment", False),
        ("import foo # test comment", "test comment", True),
        ("from foo import bar # test comment", "test comment", True),
        ("import foo", None, False),
        ("import foo as bar", None, False),
        ("from foo import bar, bar2", None, False),
        ("from foo import bar, bar2, baz, quux, abc, defg, lmo, pqr, nmp, qrs, ghi, jkl", None, False),
    ]
)
def test_ImportStatement_with_comments(text, comment, should_keep):
    """Test that the ImportStatement._from_str correctly handles comments."""
    imp_stmt = ImportStatement._from_str(text)
    pretty = imp_stmt.pretty_print().split("\n")

    if comment is None:
        assert all(line_comment is None for line_comment in imp_stmt.comments)

    else:
        assert comment in text
        assert any(comment in line for line in imp_stmt.comments if line)

        if should_keep:
            # Should only be kept if it's on the first line
            assert comment in pretty[0]
            assert not any(comment in line for line in pretty[1:])

            # Should only appear in 1 import statement comment; others comments are None
            comments = [item for item in imp_stmt.comments if item is not None]
            assert len(comments) == 1
            assert comment in comments[0]
        else:
            assert not any(comment in line for line in pretty)
