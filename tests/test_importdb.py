# pyflyby/test_importdb.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import os

from   pyflyby._importclns      import ImportMap, ImportSet
from   pyflyby._importdb        import ImportDB
from   pyflyby._importstmt      import Import


PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")
os.environ["PYFLYBY_PATH"] = ".../.pyflyby:" + os.path.join(PYFLYBY_HOME, "etc/pyflyby")
os.environ["PYFLYBY_KNOWN_IMPORTS_PATH"] = ""
os.environ["PYFLYBY_MANDATORY_IMPORTS_PATH"] = ""


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


def test_global_import_db_1():
    db = ImportDB.get_default('.')
    assert isinstance(db, ImportDB)
    assert ImportDB(db) is db


def test_global_import_db_pyflyby_1():
    import pyflyby
    db = ImportDB.get_default(pyflyby.__file__)
    assert isinstance(db, ImportDB)
    result = db.by_fullname_or_import_as["FileText"]
    expected = (Import('from pyflyby._file import FileText'),)
    assert result == expected
