# pyflyby/test_importdb.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import os
from   shutil                   import rmtree
import sys
from   tempfile                 import NamedTemporaryFile, mkdtemp
from   textwrap                 import dedent

from   pyflyby._importclns      import ImportMap, ImportSet
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import Import
from   pyflyby._util            import EnvVarCtx

from   contextlib               import contextmanager


if sys.version_info > (3, 11):
    from contextlib import chdir

else:

    @contextmanager
    def chdir(path):
        old = os.getcwd()
        try:
            os.chdir(path)
            yield
        finally:
            os.chdir(old)


def test_importDB_root():
    """
    See #362
    """
    with chdir("/"):
        ImportDB.get_default(None)

def test_ImportDB_from_code_1():
    db = ImportDB('from aa.bb import cc as dd, ee')
    expected_known = ImportSet(['from aa.bb import cc as dd, ee'])
    assert db.known_imports == expected_known


def test_ImportDB_from_code_complex_1():
    result = ImportDB('''
        import foo, bar as barf
        from xx import yy, yyy, yyyy
        __mandatory_imports__ = ['__future__.division',
                                 'import aa . bb . cc as dd']
        __forget_imports__ = ['xx.yy', 'from xx import zz']
        __canonical_imports__ = {'bad.baad': 'good.goood'}
    ''')
    assert result.known_imports == ImportSet([
        "import foo",
        "import bar as barf",
        "from xx import yyy, yyyy"
        ])
    assert result.mandatory_imports == ImportSet([
        "from __future__ import division",
        "from aa.bb import cc as dd"])
    assert result.forget_imports == ImportSet([
        "from xx import yy",
        "from xx import zz"])
    assert result.canonical_imports == ImportMap({
        "bad.baad": "good.goood"
    })


def test_ImportDB_by_fullname_or_import_as_1():
    db = ImportDB('from aa.bb import cc as dd')
    result = db.by_fullname_or_import_as
    expected = {
        'aa': (Import('import aa'),),
        'aa.bb': (Import('import aa.bb'),),
        'dd': (Import('from aa.bb import cc as dd'),)
    }
    assert result == expected


def test_ImportDB_get_default_1():
    db = ImportDB.get_default('.')
    assert isinstance(db, ImportDB)
    assert ImportDB(db) is db


def import_ImportDB_memoized_1():
    db1 = ImportDB.get_default('.')
    db2 = ImportDB.get_default('.')
    assert db1 is db2


def test_ImportDB_pyflyby_path_filename_1():
    # Check that PYFLYBY_PATH set to a filename works.
    with NamedTemporaryFile(mode='w+') as f:
        f.write("from m4065635 import f78841936, f44111337, f73485346\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            db = ImportDB.get_default('/bin')
        assert isinstance(db, ImportDB)
        result = db.by_fullname_or_import_as["f44111337"]
        expected = (Import('from m4065635 import f44111337'),)
        assert result == expected


def test_ImportDB_pyflyby_path_no_default_1():
    # Check that defaults can be turned off from PYFLYBY_PATH.
    with NamedTemporaryFile(mode='w+') as f:
        f.write("from m27056973 import f8855924\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            db = ImportDB.get_default('/bin')
        assert isinstance(db, ImportDB)
        result = db.by_fullname_or_import_as["f8855924"]
        expected = (Import('from m27056973 import f8855924'),)
        assert result == expected
        assert "defaultdict" not in db.by_fullname_or_import_as
        expected_bfoia = {
            "f8855924": (Import("from m27056973 import f8855924"),),
            "m27056973": (Import("import m27056973"),),
        }
        assert db.by_fullname_or_import_as == expected_bfoia
    # For the default PYFLYBY_PATH (configured in conftest.py), we should have
    # defaultdict.
    db2 = ImportDB.get_default('/bin')
    result = db2.by_fullname_or_import_as["defaultdict"]
    expected = (Import('from collections import defaultdict'),)
    assert result == expected


def test_ImportDB_pyflyby_path_change_1():
    # Check that memoization takes into account changes in
    # os.environ["PYFLYBY_PATH"].
    with NamedTemporaryFile(mode='w+') as f:
        f.write("from m60309242 import f5781152\n")
        f.flush()
        with EnvVarCtx(PYFLYBY_PATH=f.name):
            db = ImportDB.get_default('/bin')
        result = db.by_fullname_or_import_as["f5781152"]
        expected = (Import('from m60309242 import f5781152'),)
        assert result == expected
        db2 = ImportDB.get_default('/bin')
        assert db2 is not db
        assert "f5781152" not in db2.by_fullname_or_import_as


def test_ImportDB_pyflyby_recurse_dir_1():
    d = mkdtemp(prefix=".", suffix="_pyflyby")
    with EnvVarCtx(PYFLYBY_PATH=d):
        os.mkdir("%s/d1"%d)
        os.mkdir("%s/d1/d2"%d)
        os.mkdir("%s/d1/d2/d3"%d)
        os.mkdir("%s/.d4"%d)
        with open("%s/d1/d2/d3/f6446612.py"%d, 'w') as f:
            f.write("from m7540535 import f17684046, f7241844")
        with open("%s/d1/d2/d3/f91456848"%d, 'w') as f: # missing ".py"
            f.write("from m5733351 import f17684046, f7241844")
        with open("%s/.d4/f52247912.py"%d, 'w') as f: # under a dot dir
            f.write("from m50938634 import f17684046, f7241844")
        db = ImportDB.get_default("/bin")
        result = db.by_fullname_or_import_as["f7241844"]
        expected = (Import("from m7540535 import f7241844"),)
        assert result == expected
        rmtree(d)


def test_ImportDB_pyflyby_dotdotdot_1():
    with EnvVarCtx(PYFLYBY_PATH=".../f1198375"):
        d = mkdtemp("_pyflyby")
        os.mkdir("%s/d1"%d)
        os.mkdir("%s/d1/d2"%d)
        os.mkdir("%s/d1/d2/d3"%d)
        with open("%s/f1198375"%d, 'w') as f:
            f.write("from m97722423 import f49463937, f3532073\n")
        with open("%s/d1/d2/f1198375"%d, 'w') as f:
            f.write("from m90927291 import f6273971, f49463937\n")
        db = ImportDB.get_default("%s/d1/d2/d3/f"%d)
        result = db.by_fullname_or_import_as["f49463937"]
        expected = (
            Import("from m90927291 import f49463937"),
            Import("from m97722423 import f49463937"),
        )
        assert result == expected
        rmtree(d)


def test_ImportDB_pyflyby_forget_1():
    with EnvVarCtx(PYFLYBY_PATH=".../f70301376"):
        d = mkdtemp("_pyflyby")
        os.mkdir("%s/d1"%d)
        os.mkdir("%s/d1/d2"%d)
        os.mkdir("%s/d1/d2/d3"%d)
        with open("%s/f70301376"%d, 'w') as f:
            f.write(dedent("""
                from m49790901       import f27626336, f96186952
                from m78687343       import f35156295, f43613649
                from m78687343.a.b.c import f54583581
                from m49790901.a     import f27626336, f96186952
            """))
        with open("%s/d1/d2/f70301376"%d, 'w') as f:
            f.write(dedent("""
                __forget_imports__ = [
                   'from m49790901 import f27626336',
                   'from m78687343 import *',
                ]
            """))
        db = ImportDB.get_default("%s/d1/d2/d3/f"%d)
        result = db.known_imports
        expected = ImportSet("""
                from m49790901       import f96186952
                from m49790901.a     import f27626336, f96186952
        """)
        assert result == expected
        rmtree(d)
