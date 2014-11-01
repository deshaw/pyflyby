# pyflyby/test_autoimp.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import ast
import os
import pytest

from   pyflyby._autoimp         import (auto_eval, find_missing_imports,
                                        load_symbol)


def test_find_missing_imports_basic_1():
    result   = find_missing_imports("os.path.join", namespaces=[])
    expected = ["os.path.join"]
    assert result == expected


def test_find_missing_imports_in_namespace_1():
    result   = find_missing_imports("os.path.join", namespaces=[{"os":os}])
    expected = []
    assert result == expected


def test_find_missing_imports_builtins_1():
    result   = find_missing_imports("os, sys, eval", [{"os": os}])
    expected = ['sys']
    assert result == expected


def test_find_missing_imports_undefined_1():
    result   = find_missing_imports("numpy.arange(x) + arange(y)", [{"y": 3}])
    expected = ['arange', 'numpy.arange', 'x']
    assert result == expected


def test_find_missing_imports_in_scope_1():
    result   = find_missing_imports("import numpy; numpy.arange(x) + arange(x)", [])
    expected = ['arange', 'x']
    assert result == expected


def test_find_missing_imports_in_scope_2():
    result   = find_missing_imports("from numpy import pi; numpy.pi + pi + x", [])
    expected = ['numpy.pi', 'x']
    assert result == expected


def test_find_missing_imports_in_scope_3():
    result   = find_missing_imports("for x in range(3): print numpy.arange(x)", [])
    expected = ['numpy.arange']
    assert result == expected


def test_find_missing_imports_in_scope_funcall_1():
    result   = find_missing_imports("foo1 = func(); foo1.bar + foo2.bar", [])
    expected = ['foo2.bar', 'func']
    assert result == expected


def test_find_missing_imports_in_scope_assign_attr_1():
    result   = find_missing_imports("a.b.y = 1; a.b.x, a.b.y, a.b.z", [])
    expected = ['a.b.x', 'a.b.z']
    assert result == expected


def test_find_missing_imports_lambda_1():
    result   = find_missing_imports("(lambda x: x*x)(7)", [])
    expected = []
    assert result == expected


def test_find_missing_imports_lambda_2():
    result   = find_missing_imports("(lambda x: x*x)(7) + x", [])
    expected = ['x']
    assert result == expected


def test_find_missing_imports_list_comprehension_1():
    result   = find_missing_imports("[x+y+z for x,y in [(1,2)]], y", [])
    expected = ['z']
    assert result == expected


def test_find_missing_imports_generator_expression_1():
    result   = find_missing_imports("(x+y+z for x,y in [(1,2)]), y", [])
    expected = ['y', 'z']
    assert result == expected


def test_find_missing_imports_qualified_1():
    result   = find_missing_imports("( ( a . b ) . x ) . y + ( c + d ) . x . y", [])
    expected = ['a.b.x.y', 'c', 'd']
    assert result == expected


def test_find_missing_imports_ast_1():
    node = ast.parse("import numpy; numpy.arange(x) + arange(x)")
    result   = find_missing_imports(node, [])
    expected = ['arange', 'x']
    assert result == expected


def test_find_missing_imports_print_function_1():
    node = ast.parse(
        "from __future__ import print_function\n"
        "print (42, file=sys.stdout)\n"
    )
    result   = find_missing_imports(node, [])
    expected = ['sys.stdout']
    assert result == expected


def test_find_missing_imports_code_1():
    f = lambda: foo.bar(x) + baz(y)
    result   = find_missing_imports(f.func_code, [])
    expected = ['baz', 'foo.bar', 'x', 'y']
    assert result == expected


def test_find_missing_imports_code_args_1():
    def f(x, y, *a, **k):
        return g(x, y, z, a, k)
    result   = find_missing_imports(f.func_code, [])
    expected = ['g', 'z']
    assert result == expected


def test_find_missing_imports_code_use_after_import_1():
    def f():
        import foo
        foo.bar()
    result   = find_missing_imports(f.func_code, [])
    expected = []
    assert result == expected


def test_find_missing_imports_code_lambda_scope_1():
    f = lambda x: (lambda: x+y)
    result   = find_missing_imports(f.func_code, [])
    expected = ['y']
    assert result == expected


def test_find_missing_imports_code_conditional_1():
    def f():
        y0 = x0
        if c:
            y1 = y0 + x1
        else:
            y2 = x2 + y0
        x3 + y0
        y1 + y2
    result   = find_missing_imports(f.func_code, [])
    expected = ['c', 'x0', 'x1', 'x2', 'x3']
    assert result == expected


def test_find_missing_imports_code_loop_1():
    def f():
        for i in range(10):
            if i > 0:
                use(x)
                use(y)
            else:
                x = "hello"
    result   = find_missing_imports(f.func_code, [])
    expected = ['use', 'y']
    assert result == expected


def test_load_symbol_1():
    assert load_symbol("os.path.join", {"os": os}) is os.path.join


def test_load_symbol_2():
    assert load_symbol("os.path.join.func_name", {"os": os}) == "join"


def test_load_symbol_missing_1():
    with pytest.raises(AttributeError):
        load_symbol("os.path.join.asdfasdf", {"os": os})


def test_load_symbol_missing_2():
    with pytest.raises(AttributeError):
        load_symbol("os.path.join", {})


def test_auto_eval_1():
    result = auto_eval("b64decode('aGVsbG8=')")
    assert result == 'hello'


def test_auto_eval_locals_import_1():
    mylocals = {}
    result = auto_eval("b64decode('aGVsbG8=')", locals=mylocals)
    assert result == 'hello'
    assert mylocals["b64decode"] is __import__("base64").b64decode


def test_auto_eval_globals_import_1():
    myglobals = {}
    result = auto_eval("b64decode('aGVsbG8=')", globals=myglobals)
    assert result == 'hello'
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
    assert mylocals['x'] == ['hello']
    assert mylocals["b64decode"] is __import__("base64").b64decode
