# pyflyby/test_importstmt.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   pyflyby._flags           import CompilerFlags
from   pyflyby._importstmt      import Import, ImportSplit, ImportStatement


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
