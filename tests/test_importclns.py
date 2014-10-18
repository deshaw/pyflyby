# pyflyby/test_importclns.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

from   pyflyby.importclns       import ImportMap, ImportSet
from   pyflyby.importstmt       import Import


def test_ImportSet_1():
    importset = ImportSet('''
        from m1 import f1
        from m2 import f1
        from m1 import f2
        from m1 import f1, f3
        import m3.m4 as m34
    ''')
    expected = (
        Import("from m1 import f1"),
        Import("from m1 import f2"),
        Import("from m1 import f3"),
        Import("from m2 import f1"),
        Import("from m3 import m4 as m34"))
    print importset.imports
    assert importset.imports == expected
    assert len(importset) == 5


def test_ImportSet_ignore_shadowed_1():
    importset = ImportSet('''
        from m1 import f1, f2, f3
        from m2 import f2, f4, f6
        from m3 import f3, f6, f9
        from m1 import f9
    ''', ignore_shadowed=True)
    expected = (
        Import("from m1 import f1"),
        Import("from m1 import f9"),
        Import("from m2 import f2"),
        Import("from m2 import f4"),
        Import("from m3 import f3"),
        Import("from m3 import f6"),
    )
    print importset.imports
    assert importset.imports == expected
    assert len(importset) == 6


def test_ImportSet_contains_1():
    importset = ImportSet('''
        from m1 import f1
        from m2 import f1
        from m1 import f2
        from m1 import f1, f3
        import m3.m4 as m34
    ''')
    assert Import("from  m1 import f1")     in importset
    assert Import("from .m1 import f1") not in importset
    assert Import("from  m2 import f2") not in importset


def test_ImportSet_by_import_as_1():
    importset = ImportSet('''
        from a1.b1 import c1 as x
        from a2.b2 import c2 as x
        from a2.b2 import c2 as y
    ''')
    expected = {'x': (Import('from a1.b1 import c1 as x'),
                      Import('from a2.b2 import c2 as x')),
                'y': (Import('from a2.b2 import c2 as y'),)}
    assert importset.by_import_as == expected


def test_ImportSet_member_names_1():
    importset = ImportSet('''
        import numpy.linalg.info
        from sys import exit as EXIT
    ''')
    expected = {
        '': ('EXIT', 'numpy', 'sys'),
        'numpy': ('linalg',),
        'numpy.linalg': ('info',),
        'sys': ('exit',)
    }
    assert importset.member_names == expected


def test_ImportSet_conflicting_imports_1():
    importset = ImportSet('import b\nfrom f import a as b\n')
    assert importset.conflicting_imports == ('b',)


def test_ImportSet_conflicting_imports_2():
    importset = ImportSet('import b\nfrom f import a\n')
    assert importset.conflicting_imports == ()



def test_ImportMap_1():
    importmap = ImportMap({'a.b': 'aa.bb', 'a.b.c': 'aa.bb.cc'})
    assert importmap['a.b'] == 'aa.bb'
