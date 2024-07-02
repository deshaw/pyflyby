# pyflyby/test_importclns.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



from   pyflyby._importclns      import ImportMap, ImportSet
from   pyflyby._importstmt      import Import, ImportStatement


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
    print(importset.imports)
    assert importset.imports == expected
    assert len(importset) == 5


def test_ImportSet_constructor_string_1():
    importset = ImportSet("from m1 import c, b; from m1 import a as a")
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    assert list(importset) == expected


def test_ImportSet_constructor_importstmt_1():
    importset = ImportSet(ImportStatement("from m1 import a, b, c"))
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    assert list(importset) == expected


def test_ImportSet_constructor_list_1():
    importset = ImportSet(["from m1 import c, b; from m1 import a as a"])
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    assert list(importset) == expected


def test_ImportSet_constructor_list_2():
    importset = ImportSet(["from m1 import c, b", "from m1 import a as a"])
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    assert list(importset) == expected


def test_ImportSet_constructor_list_imports_1():
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    importset = ImportSet(expected)
    assert list(importset) == expected


def test_ImportSet_constructor_list_importstmt_1():
    importset = ImportSet([ImportStatement("from m1 import a, b"),
                           ImportStatement("from m1 import c as c")])
    expected = [Import("from m1 import a"),
                Import("from m1 import b"),
                Import("from m1 import c")]
    assert list(importset) == expected


def test_ImportSet_constructor_idempotent_1():
    importset = ImportSet("from m1 import c, b, a")
    result = ImportSet(importset)
    assert result is importset


def test_ImportSet_eqne_1():
    s1a = ImportSet("from m1 import a, b, a, c")
    s1b = ImportSet("from m1 import c, b; from m1 import a as a")
    s2  = ImportSet("import m1.a; import m1.b; import m1.c")
    assert     (s1a == s1b)
    assert not (s1a != s1b)
    assert     (s1a != s2 )
    assert not (s1a == s2 )


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
    print(importset.imports)
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


def test_ImportSet_without_imports_1():
    importset = ImportSet("import a, b, c, d")
    result = importset.without_imports("import x, d, b, y")
    expected = ImportSet("import a, c")
    assert result == expected


def test_ImportSet_without_imports_no_action_1():
    importset = ImportSet("import a, b, c, d")
    result = importset.without_imports("import x, y")
    assert result is importset


def test_ImportSet_without_imports_from_1():
    importset = ImportSet(["from m1 import a, b",
                           "from m2 import b, c",
                           "from m3 import b, x"])
    result = importset.without_imports("from m1 import b; from m2 import b")
    expected = ImportSet(["from m1 import a",
                          "from m2 import c",
                          "from m3 import b, x"])
    assert result == expected


def test_ImportSet_without_imports_exact_1():
    importset = ImportSet(["from m1 import a",
                           "import m1.a",
                           "from m1.a import *"])
    result = importset.without_imports("from m1 import a")
    expected = ImportSet("import m1.a; from m1.a import *")
    assert result == expected


def test_ImportSet_without_imports_exact_2():
    importset = ImportSet(["from m1 import a",
                           "import m1.a",
                           "from m1.a import *"])
    result = importset.without_imports("import m1.a")
    expected = ImportSet("from m1 import a; from m1.a import *")
    assert result == expected


def test_ImportSet_without_imports_star_1():
    importset = ImportSet("""
        from m11321086.a   import f27811501, f04141733
        from m28630179.a   import f75932565, f54328537
        from m28630179.a.b import f46586889, f53411856
        from m28630179.x   import f10642186, f95537624
        from .m28630179.a  import f38714787, f42847225
    """)
    result = importset.without_imports("from m28630179.a import *")
    expected = ImportSet("""
        from m11321086.a   import f27811501, f04141733
        from m28630179.x   import f10642186, f95537624
        from .m28630179.a  import f38714787, f42847225
    """)
    assert result == expected


def test_ImportSet_without_imports_star_dot_1():
    importset = ImportSet("""
        import m94165726
        from   m68073152   import f59136817
        from   .m69396491  import f87639367
        from   .           import m81881832
        from   m97513719.a import f42218372
    """)
    result = importset.without_imports("from . import *")
    expected = ImportSet("""
        import m94165726
        from   m68073152   import f59136817
        from   m97513719.a import f42218372
    """)
    assert result == expected


def test_ImportMap_1():
    importmap = ImportMap({'a.b': 'aa.bb', 'a.b.c': 'aa.bb.cc'})
    assert importmap['a.b'] == 'aa.bb'

def test_ImportSet_union():
    a = ImportSet('from numpy import einsum, cos')
    b = ImportSet('from numpy import sin, cos')
    c = ImportSet('from numpy import einsum, sin, cos')
    assert a|b == c
