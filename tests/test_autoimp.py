# pyflyby/test_autoimp.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/



import ast
import os
import pytest
from   shutil                   import rmtree
import sys
from   tempfile                 import mkdtemp
from   textwrap                 import dedent

from   pyflyby                  import (Filename, ImportDB, auto_eval,
                                        auto_import, find_missing_imports)
from   pyflyby._autoimp         import (LoadSymbolError, load_symbol,
                                        scan_for_import_issues)
from   pyflyby._flags           import CompilerFlags
from   pyflyby._idents          import DottedIdentifier
from   pyflyby._importstmt      import Import
from   pyflyby._util            import CwdCtx


@pytest.fixture
def tpp(request):
    """
    A temporary directory which is temporarily added to sys.path.
    """
    d = mkdtemp(prefix="pyflyby_test_autoimp_", suffix=".tmp")
    d = Filename(d).real
    def cleanup():
        # Unload temp modules.
        for name, module in sorted(sys.modules.items()):
            if (getattr(module, "__file__", None) or "").startswith(str(d)):
                del sys.modules[name]
        # Clean up sys.path.
        sys.path.remove(str(d))
        # Clean up directory on disk.
        rmtree(str(d))
    request.addfinalizer(cleanup)
    sys.path.append(str(d))
    return d


def writetext(filename, text, mode='w'):
    text = dedent(text)
    assert isinstance(filename, Filename)
    with open(str(filename), mode) as f:
        f.write(text)
    return filename


def _dilist2strlist(arg):
    assert type(arg) is list
    assert all(type(x) is DottedIdentifier for x in arg)
    return list(map(str, arg))


def test_find_missing_imports_basic_1():
    result   = find_missing_imports("os.path.join", namespaces=[{}])
    result   = _dilist2strlist(result)
    expected = ["os.path.join"]
    assert expected == result


def test_find_missing_imports_in_namespace_1():
    result   = find_missing_imports("os.path.join", namespaces=[{"os":os}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_builtins_1():
    result   = find_missing_imports("os, sys, eval", [{"os": os}])
    result   = _dilist2strlist(result)
    expected = ['sys']
    assert expected == result


def test_find_missing_imports_undefined_1():
    result   = find_missing_imports("numpy.arange(x) + arange(y)", [{"y": 3}])
    result   = _dilist2strlist(result)
    expected = ['arange', 'numpy.arange', 'x']
    assert expected == result


def test_find_missing_imports_in_scope_1():
    result   = find_missing_imports("import numpy; numpy.arange(x) + arange(x)", [{}])
    result   = _dilist2strlist(result)
    expected = ['arange', 'x']
    assert expected == result


def test_find_missing_imports_in_scope_2():
    result   = find_missing_imports("from numpy import pi; numpy.pi + pi + x", [{}])
    result   = _dilist2strlist(result)
    expected = ['numpy.pi', 'x']
    assert expected == result


def test_find_missing_imports_in_scope_3():
    result   = find_missing_imports("for x in range(3): print(numpy.arange(x))", [{}])
    result   = _dilist2strlist(result)
    expected = ['numpy.arange']
    assert expected == result


def test_find_missing_imports_in_scope_funcall_1():
    result   = find_missing_imports("foo1 = func(); foo1.bar + foo2.bar", [{}])
    result   = _dilist2strlist(result)
    expected = ['foo2.bar', 'func']
    assert expected == result


def test_find_missing_imports_in_scope_assign_attr_1():
    result   = find_missing_imports("a.b.y = 1; a.b.x, a.b.y, a.b.z", [{}])
    result   = _dilist2strlist(result)
    expected = ['a.b.x', 'a.b.z']
    assert expected == result


def test_find_missing_imports_lambda_1():
    result   = find_missing_imports("(lambda x: x*x)(7)", [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_lambda_2():
    result   = find_missing_imports("(lambda x: x*x)(7) + x", [{}])
    result   = _dilist2strlist(result)
    expected = ['x']
    assert expected == result


def test_find_missing_imports_lambda_3():
    result   = find_missing_imports("(lambda *a,**k: (a, k))(7, x=1)", [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_list_comprehension_1():
    result   = find_missing_imports("[x+y+z for x,y in [(1,2)]], y", [{}])
    result   = _dilist2strlist(result)
    expected = ['y', 'z']
    assert expected == result


def test_find_missing_imports_list_comprehension_nested_tuple_1():
    result   = find_missing_imports("[w+x+y+z for x,(y,z) in []]", [{}])
    result   = _dilist2strlist(result)
    expected = ['w']
    assert expected == result


def test_find_missing_imports_list_comprehension_nested_tuple_2():
    result   = find_missing_imports(
        "[a+A+b+B+c+C+d+D+e+E+f+F+g+G for a,((b,c),d,[e,f,(g,)]) in []]", [{}])
    result   = _dilist2strlist(result)
    expected = ['A','B','C','D','E','F','G']
    assert expected == result


def test_find_missing_imports_generator_expression_1():
    result   = find_missing_imports("(x+y+z for x,y in [(1,2)]), y", [{}])
    result   = _dilist2strlist(result)
    expected = ['y', 'z']
    assert expected == result


def test_find_missing_imports_qualified_1():
    result   = find_missing_imports("( ( a . b ) . x ) . y + ( c + d ) . x . y", [{}])
    result   = _dilist2strlist(result)
    expected = ['a.b.x.y', 'c', 'd']
    assert expected == result


def test_find_missing_imports_ast_1():
    node = ast.parse("import numpy; numpy.arange(x) + arange(x)")
    result   = find_missing_imports(node, [{}])
    result   = _dilist2strlist(result)
    expected = ['arange', 'x']
    assert expected == result


def test_find_missing_imports_print_function_1():
    node = ast.parse(
        "from __future__ import print_function\n"
        "print (42, file=sys.stdout)\n"
    )
    result   = find_missing_imports(node, [{}])
    result   = _dilist2strlist(result)
    expected = ['sys.stdout']
    assert expected == result


def test_find_missing_imports_assignment_1():
    code = dedent("""
        from __future__ import print_function

        def f():
            x = 1
            print(x, y, z)
            y = 2
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y', 'z']
    assert expected == result


def test_find_missing_imports_function_body_1():
    code = dedent("""
        x1 = 1
        def func59399065():
            return x1 + x2 + x3
        x3 = 3
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['x2']
    assert expected == result


def test_find_missing_imports_function_paramlist_1():
    code = dedent("""
        X1 = 1
        def func85025862(x1=X1, x2=X2, x3=X3):
            return x1 + x2 + x3
        X3 = 3
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['X2', 'X3']
    assert expected == result


def test_find_missing_imports_function_paramlist_2():
    code = dedent("""
        from somewhere import given, data

        @given(data())
        def blargh(data):
            pass
    """)
    result  = find_missing_imports(code, [{}])
    result  = _dilist2strlist(result)
    expected = []
    assert expected == result

def test_find_missing_imports_function_defaults_1():
    code = dedent("""
        e = 1
        def func32466773(a=b, b=c, c=a, d=d, e=e, f=1):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b', 'c', 'd']
    assert expected == result


def test_find_missing_imports_function_defaults_kwargs_1():
    code = dedent("""
        def func16049151(x=args, y=kwargs, z=y, *args, **kwargs):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['args', 'kwargs', 'y']
    assert expected == result


def test_find_missing_imports_kwarg_annotate():
    """
    pfb issue 162
    """
    code = dedent("""
        def func_pfb162(args:Dict, **kwargs:Any):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Any', 'Dict']
    assert expected == result


def test_find_missing_imports_function_defaults_kwargs_2():
    code = dedent("""
        args = 1
        kwargs = 2
        def func69790319(x=args, y=kwargs, z=y, *args, **kwargs):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_function_paramlist_local_1():
    code = dedent("""
        x1 = 1
        x2 = 2
        def func77361554(x1, x3, x4):
            pass
        x4 = 4
        x1, x2, x3, x4, x5
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['x3', 'x5']
    assert expected == result


def test_find_missing_imports_function_paramlist_selfref_1():
    code = dedent("""
        f1 = 'x'
        def f2(g1=f1, g2=f2, g3=f3):
            return (g1, g2, g3)
        f3 = 'x'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['f2', 'f3']
    assert expected == result


def test_find_missing_imports_function_paramlist_lambda_1():
    code = dedent("""
        X1 = 1
        def func85025862(x1=lambda: 1/X1, x2=lambda: 1/X2, x3=lambda: 1/X3):
            return x1() + x2() + x3()
        X3 = 3
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['X2']
    assert expected == result


def test_find_missing_imports_decorator_1():
    code = dedent("""
        deco1 = 'x'
        @deco1
        @deco2
        @deco3
        def func33144383():
            pass
        deco3 = 'x'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['deco2', 'deco3']
    assert expected == result


def test_find_missing_imports_decorator_selfref_1():
    code = dedent("""
        deco = 'x'
        func1 = 'x'
        @deco(func1, func2, func3)
        def func2():
            pass
        func3 = 'x'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['func2', 'func3']
    assert expected == result


def test_find_missing_imports_decorator_paramlist_1():
    code = dedent("""
        p2 = 2
        def deco(*args): pass
        @deco(p1, p2, p3)
        def foo74632516():
            pass
        p3 = 3
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['p1', 'p3']
    assert expected == result


def test_find_missing_imports_setattr_1():
    code = dedent("""
        aa = 1
        aa.xx.yy = 1
        bb.xx.yy = 1
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    # For now we intentionally don't auto-import 'bb' because that's more
    # likely to be a mistake.
    expected = []
    assert expected == result


def test_find_missing_imports_delattr_1():
    code = dedent("""
        foo1 = 1
        del foo1.bar, foo2.bar
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['foo2']
    assert expected == result


def test_find_missing_imports_delitem_lhs_1():
    code = dedent("""
        foo1 = 1
        del foo1[123], foo2[123]
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['foo2']
    assert expected == result


def test_find_missing_imports_delitem_rhs_1():
    code = dedent("""
        foo1 = 1
        bar1 = 1
        del foo1[bar1], foo1[bar2]
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['bar2']
    assert expected == result

# TODO: unit tests for local, nonlocal


def test_find_missing_imports_classdef_1():
    code = dedent("""
        class Mahopac:
            pass
        class Gleneida(Mahopac):
            pass
        Mahopac, Carmel, Gleneida
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Carmel']
    assert expected == result


def test_find_missing_imports_class_base_1():
    code = dedent("""
        Mill = object
        class Mohansic(Crom, Mill):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Crom']
    assert expected == result


def test_find_missing_imports_class_name_2():
    code = dedent(
        """
        class Decimal:
            def foo(self):

                Decimal.x = 1
    """
    )
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = []
    assert expected == result


@pytest.mark.xfail(strict=True)
def test_find_missing_import_xfail_after_pr_152():
    code = dedent(
        """
        class MyClass(object):
            Outer = MyClass
    """
    )
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ["MyClass"]
    assert result == expected


def test_method_reference_current_class():
    """
    A method can reference the current class

    But only if this is a toplevel class, nesting won't work in Python.
    """
    code = dedent(
        """
       class Decimal:
           def foo(self):
               Decimal.x = 1
               Float.y=1

           class Real:

               def foo():
                   Real.r = 1
   """
    )
    missing, unused = scan_for_import_issues(code, [{}])
    # result = _dilist2strlist(result)
    assert missing == [
        (5, DottedIdentifier("Float.y")),
        (10, DottedIdentifier("Real.r")),
    ]
    assert unused == []


def test_annotation_inside_class():
    code = dedent(
        """
        class A:
            param1: str
            param2: B

        class B:
            param1: str
   """
    )
    missing, unused = scan_for_import_issues(code, [{}])
    assert missing == []
    assert unused == []


@pytest.mark.xfail(
    reason="Had to deactivate as part of https://github.com/deshaw/pyflyby/pull/269/files conflicting requirements",
    strict=True,
)
def test_find_missing_imports_class_name_1():
    code = dedent(
        """
        class Corinne:
            pass
        class Bobtail:
            class Chippewa:
                Bobtail # will be name error at runtime
            Rockton = Passall, Corinne, Chippewa
                      # ^error, ^ok   , ^ok
    """
    )
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ["Bobtail", "Passall"]
    assert expected == result


def test_find_missing_imports_class_name_1b():
    code = dedent(
        """
        class Corinne:
            pass
        class Bobtail:
            class Chippewa:
                Bobtail # will be name error at runtime
            Rockton = Passall, Corinne, Chippewa
                      # ^error, ^ok   , ^ok
    """
    )
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ["Passall"]
    assert expected == result



def test_find_missing_imports_class_members_1():
    code = dedent("""
        class Kenosha(object):
            x = 3
            z = x, y
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_class_member_vs_function_1():
    code = dedent("""
        class Sidney(object):
            x = 3
            def barracuda(self):
                return x, y
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['x', 'y']
    assert expected == result


def test_find_missing_imports_class_member_vs_function_2():
    code = dedent("""
        class Wayne: pass
        class Connaught(object):
            class Windsor: pass
            def Mercury(self):
                return Wayne, Connaught, Windsor
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Windsor']
    assert expected == result


def test_find_missing_imports_class_member_vs_lambda_1():
    code = dedent("""
        x1 = 1
        class Salsa(object):
            x2 = 2
            x3 = 3
            y = [lambda y3=x3, y4=x4: x1 + x2 + x5 + x6]
        x4 = 4
        x5 = 5
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['x2', 'x4', 'x6']
    assert expected == result


def test_find_missing_imports_class_member_vs_paramlist_1():
    code = dedent("""
        class Drake:
            duck2 = 2
            def quack(self, mallard1=duck1, mallard2=duck2, mallard3=duck3):
                pass
            duck3 = 3
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['duck1', 'duck3']
    assert expected == result


def test_find_missing_imports_class_member_vs_paramlist_lambda_1():
    code = dedent("""
        class Breakfast:
            def corn1(self):
                pass
            def cereal(self, maize1=lambda: corn1, maize2=lambda: corn2,
                             maize3=lambda: corn3):
                return (maize1(), maize2())
            def corn2(self):
                pass
        def corn3(self):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['corn1', 'corn2']
    assert expected == result


def test_find_missing_imports_class_member_vs_paramlist_local_1():
    code = dedent("""
        class Legume:
            x1 = 1
            x2 = 2
            def func13585710(x1, x3, x4):
                pass
            x4 = 4
            y = x1, x2, x3, x4, x5
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['x3', 'x5']
    assert expected == result


def test_find_missing_imports_class_member_vs_decorator_1():
    code = dedent("""
        def deco(): 1/0
        class Cat:
            def panther1(self):
                pass
            @deco(panther1, panther2, panther3)
            def growl(self):
                pass
            def panther2(self):
                pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['panther2', 'panther3']
    assert expected == result


def test_find_missing_imports_inner_class_method_1():
    code = dedent("""
        class Sand(object):
            Dirt = 100
            class Silicon:
                def f(self):
                    return Sand, Dirt, Silicon, Glass
        class Glass:
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Dirt', 'Silicon']
    assert expected == result


def test_find_missing_imports_inner_class_attribute_1():
    code = dedent("""
        x = 100
        class Axel(object):
            a = 100
            class Beth:
                b = x + a
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a']
    assert expected == result


def test_find_missing_imports_class_member_function_ref_1():
    code = dedent("""
        class Niska(object):
            def f1(self): pass
            g = f1, f2
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['f2']
    assert expected == result


def test_find_missing_imports_class_member_generator_expression_1():
    # Verify that variables leak out of list comprehensions but not out of
    # generator expressions in Python 2.
    # Verify that both can see members of the same ClassDef.
    code = dedent("""
        class Caleb(object):
            x = []
            g1 = (1 for y1 in x)
            g2 = [1 for y2 in x]
            h = [y1, y2]
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y1', 'y2']
    assert expected == result


def test_find_missing_imports_latedef_def_1():
    code = dedent("""
        def marble(x):
            return x + y + z
        z = 100
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_latedef_lambda_1():
    code = dedent("""
        granite = lambda x: x + y + z
        z = 100
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_latedef_def_def_1():
    code = dedent("""
        def twodot():
            return sterling() + haymaker() + cannon() + twodot()
        def haymaker():
            return 100
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['cannon', 'sterling']
    assert expected == result


def test_find_missing_imports_latedef_innerdef_1():
    code = dedent("""
        def kichawan(w):
            def turkey(x):
                return v + w + x + y + z
            z = 100
        v = 200
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_latedef_innerdef_2():
    code = dedent("""
        def maple(w):
            def drumgor(x):
                return v + w + x + y + z
            z = 100
        def springmere(w):
            def dorchester(x):
                return v + w + x + y + z
        v = 200
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y', 'z']
    assert expected == result


def test_find_missing_imports_latedef_classdef_1():
    code = dedent("""
        a = 100
        class Granite:
            x = a, b
            def springs(self):
                x, y, z
        b = 100
        z = 100
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b', 'x', 'y']
    assert expected == result


def test_find_missing_imports_latedef_func_class_func_1():
    code = dedent("""
        def Nellie():
            class Shelley:
                def Norman(self):
                    return Alfred, Sherry, Grover, Kirk
            Sherry = 100
        Kirk = 200
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['Alfred', 'Grover']
    assert expected == result


def test_find_missing_imports_latedef_if_1():
    code = dedent("""
        if 1:
            def cavalier():
                x, y
        if 1:
            x = 1
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_class_scope_comprehension_1():
    code = dedent("""
        class Plymouth:
            x = []
            z = list(1 for t in x+y)
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_global_1():
    code = dedent("""
        def func10663671():
            global x
            x = x + y
        x = 1
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_complex_1():
    code = dedent("""
        x = 3+4j+5+k+u'a'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['k']
    assert expected == result


def test_find_missing_imports_code_1():
    f = lambda: foo.bar(x) + baz(y) # noqa: F821
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = ['baz', 'foo.bar', 'x', 'y']
    assert expected == result


def test_find_missing_imports_code_args_1():
    def f(x, y, *a, **k):
        return g(x, y, z, a, k) # noqa: F821
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = ['g', 'z']
    assert expected == result


def test_find_missing_imports_code_use_after_import_1():
    def f():
        import foo
        foo.bar()
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_code_lambda_scope_1():
    f = lambda x: (lambda: x+y) # noqa: F821
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = ['y']
    assert expected == result


def test_find_missing_imports_code_conditional_1():
    def f():
        y0 = x0          # noqa: F821
        if c:            # noqa: F821
            y1 = y0 + x1 # noqa: F821
        else:
            y2 = x2 + y0 # noqa: F821
        x3 + y0          # noqa: F821
        y1 + y2
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = ['c', 'x0', 'x1', 'x2', 'x3']
    assert expected == result


def test_find_missing_imports_code_loop_1():
    def f():
        for i in range(10):
            if i > 0:
                use(x)     # noqa: F821
                use(y)     # noqa: F821
            else:
                x = "hello" # noqa: F841
    result   = find_missing_imports(f.__code__, [{}])
    result   = _dilist2strlist(result)
    expected = ['use', 'y']
    assert expected == result


def test_find_missing_imports_positional_only_args_1():
    code = dedent("""
        def func(x, /, y):
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_keyword_only_args_1():
    code = dedent("""
        def func(*args, kwonly=b):
            a = kwonly
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b']
    assert expected == result


def test_find_missing_imports_keyword_only_args_2():
    code = dedent("""
        def func(*args, kwonly):
            a = kwonly
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_keyword_only_args_3():
    code = dedent("""
        def func(*args, kwonly, kwonly2=b):
            a = kwonly
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b']
    assert expected == result


def test_find_missing_imports_annotations_1():
    code = dedent("""
        def func(a: b) -> c:
            d = a
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b', 'c']
    assert expected == result


def test_find_missing_imports_annotations_2():
    code = dedent("""
    a: b = c
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b', 'c']
    assert expected == result


def test_find_missing_imports_star_assignments_1():
    code = dedent("""
    a, *b = c
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['c']
    assert expected == result


def test_find_missing_imports_star_expression_1():
    code = dedent("""
    [a, *b]
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b']
    assert expected == result


def test_find_missing_imports_star_expression_2():
    code = dedent("""
    {a: 1, **b, **{c: 1}}
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b', 'c']
    assert expected == result


def test_find_missing_imports_star_expression_function_call_1():
    code = dedent("""
    f(a, *b, **c, d=e, **g)
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b', 'c', 'e', 'f', 'g']
    assert expected == result

def test_find_missing_imports_star_expression_function_call_2():
    code = dedent("""
    f(a, b=c, *d, **e)
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'c', 'd', 'e', 'f']
    assert expected == result


def test_find_missing_imports_python_3_metaclass_1():
    code = dedent("""
    class Test(metaclass=TestMeta):
        pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['TestMeta']
    assert expected == result


def test_find_missing_imports_f_string_1():
    code = dedent("""
    a = 1
    f'{a + 1} {b + 1}'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b']
    assert expected == result


def test_find_missing_imports_f_string_2():
    code = dedent("""
    a = 1
    f'{a!s} {b!r}'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['b']
    assert expected == result


def test_find_missing_imports_f_string_3():
    # Recursive format spec
    code = dedent("""
    f'{a:{b}!s}'
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b']
    assert expected == result

def test_find_missing_imports_bytes_1():
    code = dedent("""
        a = b'b'
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = []
    assert expected == result

def test_find_missing_imports_true_false_none_1():
    # These nodes changed in Python 3, make sure they are handled correctly
    code = dedent("""
    (True, False, None)
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_pattern_match_1():
    code = dedent("""
    match {"foo": 1, "bar": 2}:
        case {
            "foo": the_foo_value,
            "bar": the_bar_value,
            **rest,
        }:
            print(the_foo_value)
        case _:
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result

@pytest.mark.xfail(reason='''The way the scope work in pyflyby it is hard to define a variable...
            only in one case I believe. We would need a scope stack in `def
            visit_match_case`, but that would remove the variable definition
            when leaving the match statement.
                   ''',strict=True)
def test_find_missing_imports_pattern_match_2():
    code = dedent("""
    match {"foo": 1, "bar": 2}:
        case {
            "foo": the_foo_value,
            "bar": the_bar_value,
            **rest,
        }:
            print(the_foo_value)
        case _:
            print('here the_x_value might be unknown', the_foo_value)
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = [DottedIdentifier('the_foo_value')]
    assert expected == result


def test_find_missing_imports_pattern_match_star_args():
    """Test that *args in match/case patterns are not flagged as undefined names."""
    code = dedent("""
    match [1, 2, 3]:
        case [*args]:
            print("Matched with args:", args)
        case _:
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_pattern_match_mapping_kwargs():
    """Test that **kwargs in match/case patterns are not flagged as undefined names."""
    code = dedent("""
    match {"foo": 1}:
        case {**kwargs}:
            print("Matched with kwargs:", kwargs)
        case _:
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_pattern_match_mixed():
    """Test mixed pattern matching with multiple capture styles."""
    code = dedent("""
    match data:
        case {
            "foo": foo,
            "bar": bar,
            **rest,
        }:
            print(foo, bar, rest)
        case [head, *middle, tail]:
            print(head, middle, tail)
        case {"keys": keys}:
            print(keys)
        case _:
            pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['data']
    assert expected == result


def test_find_missing_imports_matmul_1():
    code = dedent("""
    a@b
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'b']
    assert expected == result


def test_find_missing_imports_async_await_1():
    code = dedent("""
    async def f():
        async with a as b, c as d:
            async for i in e:
                g = await h()
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'c', 'e', 'h']
    assert expected == result


def test_find_missing_imports_async_comprehension_1():
    code = dedent("""
    async def f():
        [i async for i in range(2)]
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = []
    assert expected == result


def test_find_missing_imports_yield_from_1():
    code = dedent("""
    def f():
        yield from g()
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['g']
    assert expected == result


def test_find_missing_imports_not_async_def():
    code = dedent(
        """
    async def f():
        pass
    f()
    """
    )
    result = find_missing_imports(code, [{}])
    expected = []
    assert expected == result


def test_find_missing_imports_nested_with_1():
    code = dedent("""
    with a as b, c as d:
        pass
    """)
    result   = find_missing_imports(code, [{}])
    result   = _dilist2strlist(result)
    expected = ['a', 'c']
    assert expected == result

def test_find_missing_imports_exception_1():
    code = dedent("""
    try:
        a = 1
    except:
        pass
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = []
    assert expected == result

def test_find_missing_imports_exception_2():
    code = dedent("""
    try:
        a = 1
    except SomeException:
        pass
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ['SomeException']
    assert expected == result

def test_find_missing_imports_exception_3():
    code = dedent("""
    try:
        a = 1
    except SomeException as e:
        pass
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ['SomeException']
    assert expected == result


def test_find_missing_imports_tuple_ellipsis_type_1():
    code = dedent("""
    tuple[Foo, ..., Bar]
    """)
    result = find_missing_imports(code, [{}])
    result = _dilist2strlist(result)
    expected = ['Bar', 'Foo']
    assert expected == result


def test_scan_for_import_issues_type_comment_1():
    code = dedent("""
    from typing import Sequence
    def foo(strings  # type: Sequence[str]
            ):
        pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == []

ok1 = """
class MyClass:
    def get_class(self):
        return __class__
"""

ok2 = """
class MyClass:
    @classmethod
    def get_class(cls):
        return __class__
"""
ok3 = """
class MyClass:
    @staticmethod
    def get_class():
        return __class__
"""

@pytest.mark.parametrize('data', [ok1, ok2, ok3])
def test_fix_missing_dunder_class(data):
    """

    See https://github.com/deshaw/pyflyby/issues/325
    """
    code = dedent(data)
    missing = find_missing_imports(code, [{}])
    assert missing == []

notok1 = """print(__class__)"""
notok2 = """
class NotOk:
    print(__class__)"""


@pytest.mark.parametrize('data', [notok1, notok2])
def test_ok_dunder_class(data):
    """
    See https://github.com/deshaw/pyflyby/issues/325
    """
    code = dedent(data)
    missing = find_missing_imports(code, [{}])
    assert missing == [DottedIdentifier('__class__')]



def test_scan_for_import_issues_type_comment_2():
    code = dedent("""
    from typing import Sequence
    def foo(strings):
        # type: (Sequence[str]) -> None
        pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == []


def test_scan_for_import_issues_type_comment_3():
    code = dedent("""
    def foo(strings):
        # type: (Sequence[str]) -> None
        pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == [(1, DottedIdentifier('Sequence'))]


def test_scan_for_import_issues_type_comment_4():
    code = dedent("""
    from typing import Sequence, Tuple
    def foo(strings):
        # type: (Sequence[str]) -> None
        pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == [(2, Import('from typing import Tuple'), None)]
    assert missing == []


def test_scan_for_import_issues_multiline_string_1():
    code = dedent('''
    x = (
        """
        a
        """
        # blah
        "z"
    )
    ''')
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == []

def test_scan_for_import_issues_dictcomp_missing_1():
    code = dedent("""
        y1 = y2 = 1234
        {(x1,y1,z1): (x2,y2,z2) for x1,x2 in []}
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == [(3, DottedIdentifier('z1')), (3, DottedIdentifier('z2'))]


def test_scan_for_import_issues_dictcomp_unused_1():
    code = dedent("""
        import x1, x2, x3
        {123:x3 for x1,x2 in []}
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == [(2, Import('import x1'), None), (2, Import('import x2'), None)]


def test_scan_for_import_issues_setcomp_missing_1():
    code = dedent("""
        y1 = 1234
        {(x1,y1,z1) for x1,x2 in []}
    """)
    missing, unused = scan_for_import_issues(code)
    assert unused == []
    assert missing == [(3, DottedIdentifier('z1'))]


def test_scan_for_import_issues_setcomp_unused_1():
    code = dedent("""
        import x1, x2
        {x2 for x1 in []}
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == [(2, Import('import x1'), None)]


def test_scan_for_import_issues_class_subclass_imported_class_1():
    code = dedent("""
        from m1 import C1
        class C1(C1): pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == []


# This is now an XPASS, let's remove the xfail to see if it fails only on some CI version.
# # This is currently buggy.
# # The problem is that we postpone the check for C1.base = m1.C1, and by the
# # time we check it, we've already replaced the thing in the scope.
# @pytest.mark.xfail
def test_scan_for_import_issues_class_subclass_imported_class_in_func_1():
    code = dedent("""
        def f1():
            from m1 import C1
            class C1(C1): pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_use_then_del_in_func_1():
    code = dedent("""
        def f1():
            x1 = 1
            x1
            del x1
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_use_then_del_in_func_2():
    code = dedent("""
        def f1():
            x1 = 123
            print(x1); print(x2)
            del x1
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(4, DottedIdentifier('x2'))]
    assert unused == []


def test_scan_for_import_issues_del_in_func_then_use_1():
    code = dedent("""
        def f1():
            x1 = 123
            del x1
            print(x1); print(x2)
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(5, DottedIdentifier('x1')), (5, DottedIdentifier('x2'))]
    assert unused == []


def test_scan_for_import_issues_brace_identifiers_1():
    code = dedent("""
        import x1, x2, x3
        def f():
            '''{x1} {x3}'''
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == [(2, Import('import x2'), None)]


def test_scan_for_import_issues_brace_identifiers_bad_1():
    code = dedent("""
        import x1, x2, x3
        def f():
            '''{x1} {x3} {if}'''
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == [(2, Import('import x2'), None)]


def test_scan_for_import_issues_star_import_1():
    code = dedent("""
        import x1, y1
        x1, x2
        from m2 import *
        x3
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(3, DottedIdentifier('x2'))]
    assert unused == [(2, Import('import y1'), None)]


def test_scan_for_import_issues_star_import_deferred_1():
    code = dedent("""
        import x1, y1
        def f1():
            x1, x2
        from m2 import *
        def f1():
            x3
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == [(2, Import('import y1'), None)]


def test_scan_for_import_issues_star_import_local_1():
    code = dedent("""
        import x1, y1
        def f1():
            from m2 import *
            x2
        def f2():
            x3
        x1, x4
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(7, DottedIdentifier('x3')), (8, DottedIdentifier('x4'))]
    assert unused == [(2, Import('import y1'), None)]


def test_scan_for_import_issues_comprehension_subscript_1():
    code = dedent("""
        x = []
        [123 for x[0] in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_comprehension_subscript_missing_1():
    code = dedent("""
        [123 for x[0] in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(2, DottedIdentifier('x'))]
    assert unused == []


def test_scan_for_import_issues_comprehension_subscript_complex_1():
    code = dedent("""
        dd = []
        [(aa,bb) for (bb, cc[0], dd[0]) in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(3, DottedIdentifier('aa')),
                       (3, DottedIdentifier('cc'))]
    assert unused == []


def test_scan_for_import_issues_comprehension_attribute_1():
    code = dedent("""
        xx = []
        [123 for xx.yy in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


@pytest.mark.xfail(strict=True)
def test_scan_for_import_issues_comprehension_attribute_missing_1():
    code = dedent("""
        [123 for xx.yy in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(3, DottedIdentifier('xx'))]
    assert unused == []

# this is now an XPASS, check that it's passing everywhere in CI
# @pytest.mark.xfail
def test_scan_for_import_issues_comprehension_attribute_complex_1():
    code = dedent("""
        dd = []
        [(aa,bb) for (bb, cc.cx, dd.dx) in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(3, DottedIdentifier('aa')),
                       (3, DottedIdentifier('cc.cx'))]
    assert unused == []


def test_scan_for_import_issues_dec_usage():
    """
    see https://github.com/deshaw/pyflyby/issues/265
    """
    code = dedent(
        """
        import random

        def repeat(times):
            def wrap(fn):
                return fn
            return wrap


        @repeat(random.choice([1, 4]))
        def foo(random):
            print(random)
    """
    )
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_comprehension_attribute_subscript_1():
    code = dedent("""
        xx = []
        [123 for xx.yy[0] in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_comprehension_attribute_subscript_missing_1():
    code = dedent("""
        [123 for xx.yy[0] in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(2, DottedIdentifier('xx.yy'))]
    assert unused == []


def test_scan_for_import_issues_comprehension_subscript_attribute_1():
    code = dedent("""
        xx = []
        [123 for xx[0].yy in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_comprehension_subscript_attribute_missing_1():
    code = dedent("""
        [123 for xx[0].yy in []]
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == [(2, DottedIdentifier('xx'))]
    assert unused == []


def test_scan_for_import_issues_generator_comprehension_subscript_attribute_1():
    code = dedent("""
        xx = []
        (123 for xx[0].yy in [])
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_set_comprehension_subscript_attribute_1():
    code = dedent("""
        xx = []
        {123 for xx[0].yy in []}
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_dict_comprehension_subscript_attribute_1():
    code = dedent("""
        xx = []
        {123:456 for xx[0].yy in []}
    """)
    missing, unused = scan_for_import_issues(code, parse_docstrings=True)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_setattr_1():
    code = dedent("""
        import aa, cc
        aa.xx.yy = 1
        bb.xx.yy = 1
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(4, DottedIdentifier('bb.xx.yy'))]
    # 'cc' should be marked as an unused-import, but 'aa' should be considered
    # used.  (This was buggy before 201907.)
    assert unused == [(2, Import('import cc'), None)]


def test_scan_for_import_issues_setattr_in_func_1():
    code = dedent("""
        import aa, cc
        def f():
            aa.xx.yy = 1
            bb.xx.yy = 1
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(5, DottedIdentifier('bb.xx.yy'))]
    # 'cc' should be marked as an unused-import, but 'aa' should be considered
    # used.  (This was buggy before 201907.)
    assert unused == [(2, Import('import cc'), None)]


def test_scan_for_import_issues_class_defined_after_use():
    code = dedent("""
    def foo():
        Bar.counter = 1

    class Bar:
        counter = 0
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == []
    assert unused == []


def test_scan_for_import_issues_class_in_type_annotation_before_definition():
    """
    Test that a class used in function parameter type annotations before
    it's defined is not reported as missing.

    This test would have failed before the fix in _remove_from_missing_imports
    that handles simple identifiers in type annotations.
    """
    code = dedent("""
    class PythonStatement:
        block: "PythonBlock"

        def from_block(cls, block: PythonBlock) -> PythonStatement:
            pass

    class PythonBlock:
        pass
    """)
    missing, unused = scan_for_import_issues(code)
    # PythonBlock should not be reported as missing even though it's used
    # in type annotations before it's defined
    assert missing == [], f"Expected no missing imports, got {missing}"
    assert unused == []


def test_setattr_is_not_unused():
    code = dedent("""
        from a import b
        def f():
            b.xx.yy = 1

    """)
    missing, unused = scan_for_import_issues(code)
    # b should be considered used
    assert missing == []
    assert unused == []


def test_all_exports_1():
    code = dedent("""
        from os import path, walk, read
        __all__ = ['path', 'rmdir', 'walk']
    """)
    missing, unused = scan_for_import_issues(code)
    # path and walk should not be unused
    assert missing == [(3, DottedIdentifier('rmdir'))]
    assert unused == [(2, Import('from os import read'), None)]


def test_all_exports_tuple_1():
    code = dedent("""
        from os import path, walk, read
        __all__ = ('path', 'rmdir', 'walk')
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(3, DottedIdentifier('rmdir'))]
    assert unused == [(2, Import('from os import read'), None)]


def test_all_exports_2():
    code = dedent("""
        from __future__ import absolute_import, division

        __all__ = ["defaultdict", "rmdir"]


        def defaultdict():
            pass
    """)
    missing, unused = scan_for_import_issues(code)
    assert missing == [(4, DottedIdentifier('rmdir'))]
    assert unused == []



def test_load_symbol_1():
    assert load_symbol("os.path.join", {"os": os}) is os.path.join


def test_load_symbol_2():
    assert load_symbol("os.path.join.__name__", {"os": os}) == "join"


def test_load_symbol_missing_1():
    with pytest.raises(LoadSymbolError):
        load_symbol("os.path.join.asdfasdf", {"os": os})


def test_load_symbol_missing_2():
    with pytest.raises(LoadSymbolError):
        load_symbol("os.path.join", {})


@pytest.mark.xfail(
    strict=True, reason="old test that was not names with test_ and never passed"
)
def test_load_symbol_eval_1():
    assert 'a/b' == load_symbol("os.path.join('a','b')", {"os": os})
    assert '/'   == load_symbol("os.path.join('a','b')[1]", {"os": os})
    assert 'A'   == load_symbol("os.path.join('a','b')[0].upper()", {"os": os})


@pytest.mark.xfail(
    strict=True, reason="old test that was not names with test_ and never passed"
)
def test_load_symbol_eval_2(capsys):
    assert '/' == load_symbol("(os.path.sep[0])", {}, autoimport=True,
                              allow_eval=True)
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import os
    """).lstrip()
    assert expected == out


def test_load_symbol_no_eval_1():
    with pytest.raises(LoadSymbolError):
        load_symbol("os.path.join('a','b')", {"os": os})
    with pytest.raises(LoadSymbolError):
        load_symbol("os.path.join('a','b')[1]", {"os": os})
    with pytest.raises(LoadSymbolError):
        load_symbol("os.path.join('a','b')[0].upper", {"os": os})


def test_load_symbol_wrap_exc_1():
    class Foo89503828(object):
        def __getattr__(self, k):
            1/0
    ns = [{"foo": Foo89503828()}]
    try:
        load_symbol("foo.bar", ns)
    except LoadSymbolError as e:
        assert type(e.__cause__) == ZeroDivisionError
    else:
        assert False


@pytest.mark.xfail(
    strict=True, reason="old test that was not names with test_ and never passed"
)
def test_load_symbol_wrap_exc_eval_1():
    def foo31617859():
        return 1 / 0

    ns = [{"foo": foo31617859()}]
    try:
        load_symbol("foo()", ns, auto_eval=True)
    except LoadSymbolError as e:
        assert type(e.__cause__) == ZeroDivisionError
    else:
        assert False


@pytest.mark.xfail(
    strict=True, reason="old test that was not names with test_ and never passed"
)
def test_load_symbol_wrap_exc_eval_getattr_1():
    class Foo15356301(object):
        def __getattr__(self, k):
            1/0
    ns = [{"foo": Foo15356301()}]
    try:
        load_symbol("foo.bar", ns, auto_eval=True)
    except LoadSymbolError as e:
        assert type(e.__cause__) == ZeroDivisionError
    else:
        assert False


def test_auto_eval_1():
    result = auto_eval("b64decode('aGVsbG8=')")
    assert result == b'hello'


def test_auto_eval_locals_import_1():
    mylocals = {}
    result = auto_eval("b64decode('aGVsbG8=')", locals=mylocals)
    assert result == b'hello'
    assert mylocals["b64decode"] is __import__("base64").b64decode


def test_auto_eval_globals_import_1():
    myglobals = {}
    result = auto_eval("b64decode('aGVsbG8=')", globals=myglobals)
    assert result == b'hello'
    assert myglobals["b64decode"] is __import__("base64").b64decode


def test_auto_eval_custom_locals_1():
    result = auto_eval("b64decode('aGVsbG8=')",
                                   locals=dict(b64decode=lambda x: "blah"))
    assert result == 'blah'


def test_auto_eval_custom_globals_1():
    result = auto_eval("b64decode('aGVsbG8=')",
                                   globals=dict(b64decode=lambda x: "blah"))
    assert result == 'blah'


def test_auto_eval_exec_1():
    mylocals = dict(x=[])
    auto_eval("if True: x.append(b64decode('aGVsbG8='))",
              locals=mylocals)
    assert mylocals['x'] == [b'hello']
    assert mylocals["b64decode"] is __import__("base64").b64decode


def test_auto_eval_no_auto_flags_ps_flagps_1(capsys):
    auto_eval("print(3.00)", flags=CompilerFlags.from_int(0), auto_flags=False)
    out, _ = capsys.readouterr()
    assert out == "3.0\n"

def test_auto_eval_no_auto_flags_ps_flag_pf1():
    with pytest.raises(SyntaxError):
        auto_eval("print 3.00", flags="print_function", auto_flags=False)


def test_auto_eval_no_auto_flags_pf_flag_pf1(capsys):
    auto_eval("print(3.00, file=sys.stdout)",
              flags="print_function", auto_flags=False)
    out, _ = capsys.readouterr()
    assert out == "[PYFLYBY] import sys\n3.0\n"


def test_auto_eval_auto_flags_ps_flagps_1(capsys):
    with pytest.raises(SyntaxError):
        auto_eval("print 3.00", flags=CompilerFlags.from_int(0), auto_flags=True)


def test_auto_eval_auto_flags_pf_flagps_1(capsys):
    auto_eval("print(3.00, file=sys.stdout)", flags=CompilerFlags.from_int(0), auto_flags=True)
    out, _ = capsys.readouterr()
    assert out == "[PYFLYBY] import sys\n3.0\n"


def test_auto_eval_auto_flags_pf_flag_pf1(capsys):
    auto_eval("print(3.00, file=sys.stdout)",
              flags=CompilerFlags("print_function"), auto_flags=True)
    out, _ = capsys.readouterr()
    assert out == "[PYFLYBY] import sys\n3.0\n"


def test_auto_eval_proxy_module_1(tpp, capsys):
    os.mkdir("%s/tornado83183065"%tpp)
    writetext(tpp/"tornado83183065/__init__.py", """
        import sys
        twister = 54170888
        class P:
            def __getattr__(self, K):
                k = K.lower()
                if k == K:
                    raise AttributeError
                else:
                    return getattr(self, k)
        p = P()
        p.__dict__ = globals()
        p._m = sys.modules[__name__]
        sys.modules[__name__] = p
    """)
    writetext(tpp/"tornado83183065/hurricane.py", """
        cyclone = 79943637
    """)
    # Verify that we can auto-import a sub-module of a proxy module.
    result = auto_eval("tornado83183065.hurricane.cyclone")
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import tornado83183065
        [PYFLYBY] import tornado83183065.hurricane
    """).lstrip()
    assert out == expected
    assert result == 79943637
    # Verify that the proxy module can do its magic stuff.
    result = auto_eval("tornado83183065.TWISTER")
    out, _ = capsys.readouterr()
    assert out == "[PYFLYBY] import tornado83183065\n"
    assert result == 54170888
    # Verify that the proxy module can do its magic stuff with a submodule
    # that's already imported.
    result = auto_eval("tornado83183065.HURRICANE.cyclone")
    out, _ = capsys.readouterr()
    assert out == "[PYFLYBY] import tornado83183065\n"
    assert result == 79943637


def test_auto_import_1(capsys):
    auto_import("sys.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import sys
    """).lstrip()
    assert expected == out


def test_auto_import_multi_1(capsys):
    auto_import("sys.asdfasdf + os.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import os
        [PYFLYBY] import sys
    """).lstrip()
    assert expected == out


def test_auto_import_nothing_1(capsys):
    auto_import("sys.asdfasdf", [{"sys":sys}])
    out, _ = capsys.readouterr()
    assert out == ""


def test_auto_import_some_1(capsys):
    auto_import("sys.asdfasdf + os.asdfasdf", [{"sys":sys}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import os
    """).lstrip()
    assert expected == out


def test_auto_import_custom_1(tpp, capsys):
    writetext(tpp/"trampoline77069527.py", """
        print('hello  world')
    """)
    auto_import("trampoline77069527.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import trampoline77069527
        hello  world
    """).lstrip()
    assert expected == out


def test_auto_import_custom_in_pkg_1(tpp, capsys):
    os.mkdir(str(tpp/"truck56331367"))
    writetext(tpp/"truck56331367/__init__.py", "")
    writetext(tpp/"truck56331367/tractor.py", """
        print('hello  there')
    """)
    auto_import("truck56331367.tractor", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import truck56331367
        [PYFLYBY] import truck56331367.tractor
        hello  there
    """).lstrip()
    assert expected == out


def test_auto_import_unknown_1(capsys):
    # Verify that if we try to access something that doesn't appear to be a
    # module, we don't attempt to import it (or at least don't log any visible
    # errors for it).
    auto_import("electron91631346.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    assert out == ""


def test_auto_import_unknown_but_in_db1(tpp, capsys):
    # Verify that if we try to access something that's in the known-imports
    # database, but it doesn't actually exist, we get a visible error for it.
    db = ImportDB('import photon70447198')
    auto_import("photon70447198.asdfasdf", [{}], db=db)
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import photon70447198
        [PYFLYBY] Error attempting to 'import photon70447198': ModuleNotFoundError: No module named 'photon70447198'
        Traceback (most recent call last):
    """).lstrip()

    assert out.startswith(expected)


def test_auto_import_fake_importerror_1(tpp, capsys):
    writetext(tpp/"proton24412521.py", """
        raise ImportError("No module named proton24412521")
    """)
    auto_import("proton24412521.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import proton24412521
        [PYFLYBY] Error attempting to 'import proton24412521': ImportError: No module named proton24412521
        Traceback (most recent call last):
    """).lstrip()
    assert out.startswith(expected)


def test_auto_import_indirect_importerror_1(tpp, capsys):
    writetext(tpp/"neutron46291483.py", """
        import baryon96446873
    """)
    auto_import("neutron46291483.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import neutron46291483
        [PYFLYBY] Error attempting to 'import neutron46291483': ModuleNotFoundError: No module named 'baryon96446873'
        Traceback (most recent call last):
    """).lstrip()

    assert out.startswith(expected)


def test_auto_import_nameerror_1(tpp, capsys):
    writetext(tpp/"lepton69688541.py", """
        foo
    """)
    auto_import("lepton69688541.asdfasdf", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import lepton69688541
        [PYFLYBY] Error attempting to 'import lepton69688541': NameError: name 'foo' is not defined
        Traceback (most recent call last):
    """).lstrip()
    assert out.startswith(expected)


def test_post_import_hook_incomplete_import():
    db = ImportDB('import glob')
    expected = Import('import glob')
    def test_hook(val):
        assert val == expected
    auto_import("glob.glob('*')", [{}], db=db, post_import_hook=test_hook)


def test_post_import_hook_alias_import():
    db = ImportDB('import numpy as np')
    expected = Import('import numpy as np')
    def test_hook(val):
        assert val == expected
    auto_import("np", [{}], db=db, post_import_hook=test_hook)


def test_post_import_hook_from_statement():
    db = ImportDB('from numpy import compat')
    expected = Import('from numpy import compat')
    def test_hook(val):
        assert val == expected
    auto_import("compat", [{}], db=db, post_import_hook=test_hook)


def test_post_import_hook_fullname():
    db = ImportDB('import numpy.compat')
    expected = Import('import numpy.compat')
    def test_hook(val):
        assert val == expected
    auto_import("numpy.compat", [{}], db=db, post_import_hook=test_hook)


def test_namespace_package(tpp, capsys):
    os.mkdir(str(tpp/'namespace_package'))
    auto_import("namespace_package", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import namespace_package
    """).lstrip()
    assert out.startswith(expected)


def test_unsafe_filename_warning(tpp, capsys):
    filepath = os.path.join(tpp._filename, 'foo#bar')
    os.mkdir(filepath)
    with CwdCtx(filepath):
        auto_import("pyflyby", [{}])
    out, _ = capsys.readouterr()
    expected = dedent("""
        [PYFLYBY] import pyflyby
    """).lstrip()
    assert out.startswith(expected)


def test_unsafe_filename_warning_II(tpp, capsys):
    filepath = os.path.join(tpp._filename, "foo#bar")
    os.mkdir(filepath)
    filepath = os.path.join(filepath, "qux#baz")
    os.mkdir(filepath)
    with CwdCtx(filepath):
        auto_import("pyflyby", [{}])
    out, _ = capsys.readouterr()
    expected = dedent(
        """
        [PYFLYBY] import pyflyby
    """
    ).lstrip()
    assert out.startswith(expected)
