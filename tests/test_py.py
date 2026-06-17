# pyflyby/test_py.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import print_function

import ast
import os
import shutil
from   shutil                   import rmtree
import subprocess
import sys
import tempfile
from   tempfile                 import NamedTemporaryFile, mkdtemp
from   textwrap                 import dedent
import venv

import pytest

from   pyflyby._dbg             import inject
from   pyflyby._file            import Filename
from   pyflyby._py              import LoggedList
from   pyflyby._util            import cached_attribute

from   tests.test_interactive   import _build_pythonpath

PYFLYBY_HOME = Filename(__file__).real.dir.dir
BIN_DIR = PYFLYBY_HOME / "bin"
PYFLYBY_PATH = PYFLYBY_HOME / "etc/pyflyby"

python = sys.executable


def flatten(args):
    result = []
    for arg in args:
        if isinstance(arg, str):
            result.append(arg)
        else:
            try:
                it = iter(arg)
            except TypeError:
                result.append(arg)
            else:
                result.extend(flatten(it))
    return result


def pipe(command, stdin="", env=None):
    if command[0] != python:
        command = (python,) + command
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env
    )
    stdout = proc.communicate(stdin)[0].strip().decode('utf-8')
    retcode = proc.returncode
    assert retcode >= 0
    return stdout, retcode


@pytest.fixture
def tmp(request):
    return _TmpFixture(request)


class _TmpFixture(object):
    def __init__(self, request):
        self._request = request

    @cached_attribute
    def dir(self):
        """
        Single memoized new_tempdir()
        """
        return self.new_tempdir()

    def new_tempdir(self):
        d = mkdtemp(prefix="pyflyby_test_", suffix=".tmp")
        self._request.addfinalizer(lambda: rmtree(d))
        return Filename(d).real



def _py_internal_1(
    args,
    stdin="",
    **environment
):
    pythonpath = _build_pythonpath(environment.pop('PYTHONPATH', []))
    pyflyby_path = environment.pop("PYFLYBY_PATH", PYFLYBY_PATH)
    environment.pop('PYTHONSTARTUP', None)

    if isinstance(pyflyby_path, str):
        pyflyby_path = Filename(pyflyby_path)

    env = dict(os.environ) | environment
    env['PYFLYBY_PATH'] = str(pyflyby_path)
    env['PYTHONPATH'] = pythonpath
    env["PYTHONSTARTUP"] = ""
    prog = str(BIN_DIR/"py")
    return pipe((prog,) + args, stdin=stdin, env=env)


def py(*args, **environment) -> str:
    """Run `py`, pipe stderr to stdout, and return the result.

    Parameters
    ----------
    *args
        Arguments to pass to `py`
    **environment
        Environment variables to set. Note that PYTHONUNBUFFERED=1 always to ensure
        consistent output when stderr gets piped to stdout

    Returns
    -------
    str
        Stderr is piped to stdout, and stdout is returned
    """
    environment.pop('PYTHONUNBUFFERED', None)
    if len(args) == 1 and isinstance(args[0], (tuple, list)):
        args = tuple(args[0])
    return _py_internal_1(args, PYTHONUNBUFFERED="1", **environment)


def writetext(filename, text, mode='w'):
    text = dedent(text)
    assert isinstance(filename, Filename)
    with open(str(filename), mode) as f:
        f.write(text)
    return filename


def test_0prefix_raw_1():
    # Verify that we're testing the virtualenv we think we are.
    result, retcode = pipe([python, "-c", "import sys; print(sys.prefix)"])
    assert retcode == 0
    expected = sys.prefix
    assert result == expected


def test_0version_1():
    # Verify that we're testing the version we think we are.
    result, retcode = py("-q", "--print", "sys.version")
    assert retcode == 0
    expected = sys.version
    assert result == expected


def test_0prefix_1():
    # Verify that we're testing the virtualenv we think we are.
    result, retcode = py("-q", "--print", "sys.prefix")
    assert retcode == 0
    expected = sys.prefix
    assert result == expected


def test_eval_1():
    result, retcode = py("--eval", "b64decode('VGhvbXBzb24=')")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('VGhvbXBzb24=')
        b'Thompson'
    """).strip()
    assert result == expected


def test_eval_single_dash_1():
    result, retcode = py("-eval", "b64decode('V29vc3Rlcg==')")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('V29vc3Rlcg==')
        b'Wooster'
    """).strip()
    assert result == expected


def test_eval_equals_1():
    result, retcode = py("--eval=b64decode('TWVyY2Vy')")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('TWVyY2Vy')
        b'Mercer'
    """).strip()
    assert result == expected


def test_eval_single_dash_equals_1():
    result, retcode = py("-eval=b64decode('VW5pdmVyc2l0eQ==')")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('VW5pdmVyc2l0eQ==')
        b'University'
    """).strip()
    assert result == expected


def test_eval_c_1():
    result, retcode = py("-c", "b64decode('QmxlZWNrZXI=')")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] b64decode('QmxlZWNrZXI=')
        b'Bleecker'
    """).strip()
    assert result == expected


def test_eval_quiet_1():
    result, retcode = py("-q", "-c", "b64decode('U3VsbGl2YW4=')")
    assert retcode == 0
    expected = "b'Sullivan'"
    assert result == expected


def test_eval_expression_1():
    result, retcode = py("--eval", "calendar.WEDNESDAY")
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.WEDNESDAY
        {WEDNESDAY}
    """).strip()
    assert result == expected


def test_eval_expression_quiet_1():
    result, retcode = py("--quiet", "--eval", "calendar.WEDNESDAY")
    assert retcode == 0
    expected = WEDNESDAY
    assert result == expected


def test_exec_1():
    result, retcode = py("-c", "if 1: print(b64decode('UHJpbmNl'))")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from base64 import b64decode
        [PYFLYBY] if 1: print(b64decode('UHJpbmNl'))
        b'Prince'
    """).strip()
    assert result == expected


def test_argv_1():
    result, retcode = py("-c", "sys.argv", "x", "y")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.argv
        ['-c', 'x', 'y']
    """).strip()
    assert result == expected


def test_argv_2():
    result, retcode = py("-c", "sys.argv", "--debug", "-x  x")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.argv
        ['-c', '--debug', '-x  x']
    """).strip()
    assert result == expected


def test_file_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write('print(("Boone", sys.argv))\n')
        f.flush()
        result, retcode = py(f.name, "a", "b")
        assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        ('Boone', [%r, 'a', 'b'])
    """).strip() % (f.name,)
    assert result == expected


@pytest.mark.parametrize("arg", [
    "--file", "-file", "file", "%file",
    "--f", "-f", "f", "%f",
    "--execfile", "-execfile", "execfile", "%execfile",
    "--execf", "-execf", "execf", "%execf",
    "--runfile", "-runfile", "runfile", "%runfile",
    "--run", "-run", "run", "%run",
])
def test_file_variants_1(arg):
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write('print(("Longfellow", sys.argv))\n')
        f.write("print(__file__)\n")
        f.flush()
        result, retcode = py(f.name, "a", "b")
        assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        ('Longfellow', [%r, 'a', 'b'])
        %s
    """).strip() % (f.name, f.name)
    assert result == expected


def test_apply_1():
    result, retcode = py("--apply", "str.upper", "'Roosevelt'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] str.upper('Roosevelt')
        'ROOSEVELT'
    """).strip()
    assert result == expected


def test_apply_stdin_1():
    result, retcode = py("--apply", "str.upper", "-", stdin=b"Eagle")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] str.upper('Eagle')
        'EAGLE'
    """).strip()
    assert result == expected


def test_apply_stdin_more_args_1():
    result, retcode = py("--apply", "str.find", "-", "'k'", stdin=b"Jackson\n")
    assert retcode == 0
    expected = dedent(r"""
        [PYFLYBY] str.find('Jackson\n', 'k')
        3
    """).strip()
    assert result == expected


def test_apply_lambda_1():
    result, retcode = py("--apply", "lambda a,b:a*b", "6", "7")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda a,b:a*b)(6, 7)
        42
    """).strip()
    assert result == expected


def test_apply_lambda_nested_1():
    result, retcode = py("--apply", "(lambda a,b: lambda c,d: a*b*c*d)(2,3)", "5", "11")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda a,b: lambda c,d: a*b*c*d)(2,3)(5, 11)
        330
    """).strip()
    assert result == expected


def test_apply_args_1():
    result, retcode = py("--apply", "round", "2.984375", "3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, 3)
        2.984
    """).strip()
    assert result == expected


def test_apply_kwargs_1():
    result, retcode = py("--apply", "round", "2.984375", "--ndigits=3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, ndigits=3)
        2.984
    """).strip()
    assert result == expected


def test_apply_kwonlyargs_1():
    result, retcode = py("--apply", "lambda x, *, y: x + y", "2", "--y=3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda x, *, y: x + y)(2, y=3)
        5
    """).strip()
    assert result == expected


def test_apply_kwonlyargs_2():
    result, retcode = py("--apply", "lambda x, *, y, z=1: x + y + z", "2", "--y=3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda x, *, y, z=1: x + y + z)(2, y=3, z=1)
        6
    """).strip()
    assert result == expected


def test_apply_print_function_1():
    result, retcode = py("--apply", "print", "50810461")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(50810461)
        50810461
    """).strip()
    assert result == expected


def test_apply_print_function_string_1():
    result, retcode = py("--apply", "print", "'Bedford'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Bedford')
        Bedford
    """).strip()
    assert result == expected


def test_apply_print_function_expression_1():
    result, retcode = py("--apply", "print", "Bedford")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Bedford')
        Bedford
    """).strip()
    assert result == expected


def test_apply_variant_1():
    result, retcode = py("--call", "round", "2.984375", "3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, 3)
        2.984
    """).strip()
    assert result == expected


def test_apply_expression_1():
    result, retcode = py("--call", "3.0.is_integer")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 3.0.is_integer()
        True
    """).strip()
    assert result == expected


def test_argmode_string_1():
    result, retcode = py("--args=string", "--apply", "print", "Barrow")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Barrow')
        Barrow
    """).strip()
    assert result == expected


def test_argmode_string_donteval_module_1():
    result, retcode = py("--args=string", "--apply", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('sys')
        sys
    """).strip()
    assert result == expected


def test_argmode_string_donteval_expression_1():
    result, retcode = py("--args=string", "--apply", "print", "1+2")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('1+2')
        1+2
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--args=string",
    "--args string",
    "--arguments=strings",
    "--arguments string",
    "--argmode strs",
    "--arg_mode=str",
    "--arg-mode=s",
])
def test_argmode_string_variants_1(args):
    result, retcode = py((args + " --apply print sys").split())
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] print('sys')
        sys
    """).strip()
    assert result == expected


def test_argmode_string_quoted_1():
    result, retcode = py("--args=string", "--apply", "print", "'Jones'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print("'Jones'")
        'Jones'
    """).strip()
    assert result == expected


def test_argmode_eval_1():
    result, retcode = py("--args=eval", "--apply", "print", "'Vandam'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Vandam')
        Vandam
    """).strip()
    assert result == expected


def test_argmode_eval_expression_1():
    result, retcode = py("--args=eval", "--apply", "print", "1+2")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(3)
        3
    """).strip()
    assert result == expected


def test_argmode_eval_unparsable_1():
    result, retcode = py("--args=eval", "--apply", "print", "29033611+")
    assert retcode == 1
    assert "29033611+: SyntaxError: invalid syntax" in result


def test_argmode_eval_modname_1():
    result, retcode = py("--args=eval", "--apply", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(<module 'sys' (built-in)>)
        <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_argmode_eval_badname_1():
    result, retcode = py("--args=eval", "--apply", "print", "foo67475309")
    assert retcode == 1
    assert "NameError: name 'foo67475309' is not defined" in result


@pytest.mark.parametrize("args", [
    "--args=eval",
    "--args eval",
    "--arguments=evaluate",
    "--arguments expression",
    "--argmode exprs",
    "--arg_mode=expr",
    "--arg-mode=e",
])
def test_argmode_eval_variants_1(args):
    result, retcode = py((args + " --apply print 5+2").split())
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] print(7)
        7
    """).strip()
    assert result == expected


def test_argmode_auto_unparsable_1():
    result, retcode = py("--args=auto", "--apply", "print", "1+")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('1+')
        1+
    """).strip()
    assert result == expected


def test_argmode_auto_expression_1():
    result, retcode = py("--args=auto", "--apply", "print", "1+2")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(3)
        3
    """).strip()
    assert result == expected


def test_argmode_auto_goodname_1():
    result, retcode = py("--args=auto", "--apply", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(<module 'sys' (built-in)>)
        <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_argmode_auto_badname_1():
    result, retcode = py("--args=auto", "--apply", "print", "foo71398671")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('foo71398671')
        foo71398671
    """).strip()
    assert result == expected


def test_argmode_auto_each_1():
    result, retcode = py("--args=auto", "--apply", "print", "7_", "7+1")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('7_', 8)
        7_ 8
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--args=auto",
    "--args auto",
    "--arguments=automatic",
    "--argmode a",
    "",
])
def test_argmode_auto_variants_1(args):
    result, retcode = py((args + " --apply print 7_ 7+1").split())
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] print('7_', 8)
        7_ 8
    """).strip()
    assert result == expected


def test_heuristic_eval_1():
    result, retcode = py("1+2")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 1+2
        3
    """).strip()
    assert result == expected


def test_heuristic_eval_concat_1():
    result, retcode = py("5 + 7")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 5 + 7
        12
    """).strip()
    assert result == expected


def test_heuristic_eval_complex_1():
    result, retcode = py("5 + 7j")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 5 + 7j
        (5+7j)
    """).strip()
    assert result == expected


def test_heuristic_eval_complex_2():
    result, retcode = py("(5+7j) ** 12")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (5+7j) ** 12
        (65602966976-150532462080j)
    """).strip()
    assert result == expected


def test_heuristic_eval_exponentiation_1():
    result, retcode = py("123**4")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 123**4
        228886641
    """).strip()
    assert result == expected


def test_heuristic_eval_with_argv_1():
    result, retcode = py(
        "for x in sys.argv[1:]: print(x.capitalize())", "canal", "grand"
    )
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] import sys
        [PYFLYBY] for x in sys.argv[1:]: print(x.capitalize())
        Canal
        Grand
    """).strip()
    assert result == expected


def test_heuristic_exec_statement_1():
    result, retcode = py("""if 1: print("Mulberry")""")
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] if 1: print("Mulberry")
        Mulberry
    """).strip()
    assert result == expected


def test_heuristic_exec_multiline_statement_1():
    result, retcode = py("""if 1:\n  print("Mott")""")
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] if 1:
        [PYFLYBY]   print("Mott")
        Mott
    """).strip()
    assert result == expected


def test_heuristic_apply_1():
    result, retcode = py("str.upper", "'Ditmars'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] str.upper('Ditmars')
        'DITMARS'
    """).strip()
    assert result == expected


def test_heuristic_apply_stdin_1():
    result, retcode = py("str.upper", "-", stdin=b"Nassau")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] str.upper('Nassau')
        'NASSAU'
    """).strip()
    assert result == expected


def test_heuristic_apply_stdin_2():
    result, retcode = py("--output=silent", "sys.stdout.write", "-", stdin=b"Downing")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write('Downing')
        Downing
    """).strip()
    assert result == expected


def test_heuristic_apply_stdin_no_eval_1():
    result, retcode = py("--output=silent", "sys.stdout.write", "-", stdin=b"3+4")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write('3+4')
        3+4
    """).strip()
    assert result == expected


def test_heuristic_apply_stdin_quiet_1():
    result, retcode = py(
        "--output=silent", "-q", "sys.stdout.write", "-", stdin=b"Houston"
    )
    assert retcode == 0
    expected = "Houston"
    assert result == expected


def test_heuristic_apply_lambda_1():
    result, retcode = py("lambda a,b:a*b", "6", "7")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] lambda a,b:a*b
        [PYFLYBY] (lambda a,b:a*b)(6, 7)
        42
    """).strip()
    assert result == expected


def test_heuristic_apply_lambda_nested_1():
    result, retcode = py("(lambda a,b: lambda c,d: a*b*c*d)(2,3)", "5", "7")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda a,b: lambda c,d: a*b*c*d)(2,3)
        [PYFLYBY] (lambda a,b: lambda c,d: a*b*c*d)(2,3)(5, 7)
        210
    """).strip()
    assert result == expected


def test_heuristic_apply_builtin_args_1():
    result, retcode = py("round", "2.984375", "3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, 3)
        2.984
    """).strip()
    assert result == expected


def test_heuristic_apply_builtin_args_2():
    result, retcode = py("round", "2.984375")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375)
        3
    """).strip()
    assert result == expected


def test_heuristic_apply_builtin_kwargs_1():
    result, retcode = py("round", "2.984375", "--ndigits=3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, ndigits=3)
        2.984
    """).strip()
    assert result == expected


def test_heuristic_apply_builtin_kwargs_separate_arg_1():
    result, retcode = py("round", "2.984375", "--ndigits", "3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(2.984375, ndigits=3)
        2.984
    """).strip()
    assert result == expected


def test_heuristic_print_1():
    result, retcode = py("print", "4", "5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(4, 5)
        4 5
    """).strip()
    assert result == expected


def test_heuristic_apply_expression_1():
    result, retcode = py("3.0.is_integer")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 3.0.is_integer()
        True
    """).strip()
    assert result == expected


def test_heuristic_apply_expression_2():
    result, retcode = py("sys.stdout.flush")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.flush()
    """).strip()
    assert result == expected


def test_heuristic_eval_expression_1():
    result, retcode = py("os.path.sep")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import os.path
        [PYFLYBY] os.path.sep
        '/'
    """).strip()
    assert result == expected


def test_heuristic_eval_expression_nonmodule_1():
    result, retcode = py("os.getcwd.__name__")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import os
        [PYFLYBY] os.getcwd.__name__
        'getcwd'
    """).strip()
    assert result == expected


def test_heuristic_apply_method_arg_1():
    result, retcode = py("float.is_integer", "3.0")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] float.is_integer(3.0)
        True
    """).strip()
    assert result == expected
    result, retcode = py("float.is_integer", "3.5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] float.is_integer(3.5)
        False
    """).strip()
    assert result == expected


def test_apply_builtin_too_few_args_1():
    result, retcode = py("round")
    assert retcode == 1
    assert "TypeError: round() missing required argument 'number' (pos 1)" in result


def test_apply_builtin_too_many_args_1():
    result, retcode = py("round", "6", "7", "8")
    assert retcode == 1
    assert "TypeError: round() takes at most 2 arguments (3 given)" in result


def test_apply_builtin_bad_kwarg_1():
    result, retcode = py("round", "2.7182", "--foo=5")
    assert retcode == 1
    if sys.version_info >= (3, 13):
        # Python 3.13 improved the wording
        msg = "TypeError: round() got an unexpected keyword argument 'foo'"
    else:
        msg = "TypeError: 'foo' is an invalid keyword argument"
    assert msg in result

if sys.version_info >= (3, 12):
    MONDAY = 'calendar.MONDA'
    TUESDAY = 'calendar.TUESDAY'
    WEDNESDAY = 'calendar.WEDNESDAY'
    THURSDAY = 'calendar.THURSDAY'
    FRIDAY = 'calendar.FRIDAY'
else:
    TUESDAY = '1'
    WEDNESDAY = '2'
    THURSDAY = '3'
    FRIDAY = '4'

def test_apply_pyfunc_posargs_1():
    result, retcode = py("calendar.weekday 2014 7 18".split())
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.weekday(2014, 7, 18)
        {FRIDAY}
    """).strip()
    assert result == expected


def test_apply_pyfunc_kwarg_1():
    result, retcode = py("calendar.weekday --year=2014 --month=7 --day=17".split())
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.weekday(2014, 7, 17)
        {THURSDAY}
    """).strip()
    assert result == expected


def test_apply_pyfunc_kwarg_disorder_1():
    result, retcode = py("calendar.weekday --day=16 --month=7 --year=2014".split())
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.weekday(2014, 7, 16)
        {WEDNESDAY}
    """).strip()
    assert result == expected


def test_apply_pyfunc_kwarg_short_1():
    result, retcode = py("calendar.weekday -m 7 -d 15 -y 2014".split())
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.weekday(2014, 7, 15)
        {TUESDAY}
    """).strip()
    assert result == expected


def test_apply_pyfunc_hybrid_args_disorder_1():
    result, retcode = py("calendar.weekday 2014 -day 15 -month 7".split())
    assert retcode == 0
    expected = dedent(f"""
        [PYFLYBY] import calendar
        [PYFLYBY] calendar.weekday(2014, 7, 15)
        {TUESDAY}
    """).strip()
    assert result == expected


def test_apply_argspec_too_few_args_1():
    result, retcode = py("base64.b64decode")
    assert retcode == 1
    assert "[PYFLYBY] missing required argument s" in result
    assert "$ py base64.b64decode s [altchars [validate]]" in result


def test_apply_argspec_too_few_args_2():
    result, retcode = py("calendar.weekday")
    assert retcode == 1
    assert "[PYFLYBY] missing required argument year" in result
    assert "$ py calendar.weekday year month day" in result


def test_apply_argspec_too_many_args_1():
    result, retcode = py("base64.b64decode", "a", "b", "c", "d")
    assert retcode == 1
    assert ("[PYFLYBY] Too many positional arguments.  "
    "Expected 1-3 positional argument(s): s, altchars, validate.  "
    "Got 4 args: a b c d") in result, result
    assert "$ py base64.b64decode s [altchars [validate]]" in result


def test_apply_argspec_too_many_args_2():
    result, retcode = py("calendar.weekday", "a", "b", "c", "d")
    assert retcode == 1
    assert ("[PYFLYBY] Too many positional arguments.  "
            "Expected 3 positional argument(s): year, month, day.  "
            "Got 4 args: a b c d") in result
    assert "$ py calendar.weekday year month day" in result


def test_apply_argspec_bad_kwarg_1():
    result, retcode = py("base64.b64decode", "x", "--christopher=sheridan")
    assert retcode == 1
    assert "[PYFLYBY] Unknown option name christopher" in result
    assert "$ py base64.b64decode s [altchars [validate]]" in result


def test_apply_dashdash_1():
    result, retcode = py("--apply", "print", "4.000", "--", "--help", "5.000")
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] print(4.0, '--help', '5.000')
        4.0 --help 5.000
    """).strip()
    assert result == expected


def test_apply_namedtuple_1():
    result, retcode = py('namedtuple("ab", "aa bb")', "3", "4")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from collections import namedtuple
        [PYFLYBY] namedtuple("ab", "aa bb")
        [PYFLYBY] namedtuple("ab", "aa bb")(3, 4)
        ab(aa=3, bb=4)
    """).strip()
    assert result == expected


def test_repr_str_1():
    result, retcode = py("'Astor'")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 'Astor'
        'Astor'
    """).strip()
    assert result == expected


def test_future_division_1():
    result, retcode = py("1/2")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 1/2
        0.5
    """).strip()
    assert result == expected


def test_integer_division_1():
    result, retcode = py("7//3")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 7//3
        2
    """).strip()
    assert result == expected


def test_print_statement_1():
    result, retcode = py("print(42)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(42)
        42
    """).strip()
    assert result == expected


def test_print_statement_sep_1():
    result, retcode = py("print", "43")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(43)
        43
    """).strip()
    assert result == expected


def test_print_function_1():
    result, retcode = py("print(44, file=sys.stdout)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(44, file=sys.stdout)
        44
    """).strip()
    assert result == expected


def test_print_function_tuple_1():
    result, retcode = py("print(5,6)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(5,6)
        5 6
    """).strip()
    assert result == expected


def test_write_1():
    with NamedTemporaryFile(mode='w+') as f:
        output, retcode = py("--output=silent", "-q", "open(%r,'w').write"%f.name, "-", stdin=b"Greenwich")
        assert retcode == 0
        assert output == ""
        result = f.read()
    expected = "Greenwich"
    assert result == expected


def test_print_args_1():
    with NamedTemporaryFile(mode="w+") as f:
        output, retcode = py(
            "-q", "print", "-", "--file=open(%r,'w')" % f.name, stdin=b"Spring"
        )
        assert retcode == 0
        assert output == ""
        result = f.read()
    expected = "Spring\n"
    assert result == expected


def test_program_help_1():
    output, retcode = py("--help")
    assert retcode == 0
    assert "--version" in output


def test_program_help_full_1():
    for arg in ["--help", "-help", "help", "--h", "-h", "--?", "-?", "?"]:
        output, retcode = py(arg)
        assert retcode == 0
        assert "--version" in output


def test_function_help_1():
    output, retcode = py("base64.b64encode", "--help")
    assert retcode == 0
    assert "s [altchars]" in output
    assert ">>> base64.b64encode(s, altchars=None)" in output
    assert "$ py base64.b64encode s [altchars]" in output
    assert "$ py base64.b64encode --s=... [--altchars=...]" in output
    assert "--version" not in output
    assert "[PYFLYBY] import base64" in output
    assert "\n  Encode the bytes-like object s using Base64 and return a bytes object." in output
    assert "binascii.b2a_base64" not in output


def test_function_help_autoimport_1():
    output, retcode = py("b64encode", "--help")
    assert retcode == 0
    assert "[PYFLYBY] from base64 import b64encode" in output
    assert "s [altchars]" in output
    assert "$ py b64encode s [altchars]" in output
    assert "binascii.b2a_base64" not in output


def test_function_help_expression_1():
    output, retcode = py("sys.stdout.write", "--help")
    assert retcode == 0
    assert '>>> sys.stdout.write(' in output
    assert "$ py sys.stdout.write " in output
    if sys.version_info > (3,12):
        assert "Write string s to stream." in output, output
    else:
        assert "Write string to stream." in output, output


def test_function_help_quote_need_parens_1():
    output, retcode = py("lambda a,b: a*b", "-h")
    assert retcode == 0
    assert ">>> (lambda a,b: a*b)(a, b)" in output
    assert "$ py 'lambda a,b: a*b' a b" in output


def test_function_help_quote_already_have_parens_1():
    output, retcode = py("(lambda a,b: a*b)", "-h")
    assert retcode == 0
    assert ">>> (lambda a,b: a*b)(a, b)" in output
    assert "$ py '(lambda a,b: a*b)' a b" in output


def test_function_help_quote_nested_lambdas_1():
    output, retcode = py("(lambda a,b: lambda c,d: a*b*c*d)(2,3)", "-h")
    assert retcode == 0
    assert ">>> (lambda a,b: lambda c,d: a*b*c*d)(2,3)(c, d)" in output
    assert "$ py '(lambda a,b: lambda c,d: a*b*c*d)(2,3)' c d" in output
    assert "$ py '(lambda a,b: lambda c,d: a*b*c*d)(2,3)' --c=... --d=..." in output


def test_help_class_init_1(tmp):
    writetext(tmp.dir/"f80166304.py", """
        class Greenpoint(object):
            def __init__(self66770013,  Milton,  * Noble,  ** India):
                pass
    """)
    writetext(tmp.dir/"p", """
        from f80166304 import Greenpoint
    """,
    )
    output, retcode = py("Greenpoint?", PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.dir / "p")
    assert retcode == 0
    assert ">>> Greenpoint(Milton, *Noble, **India)" in output


def test_help_class_init_oldclass_1(tmp):
    writetext(tmp.dir/"f20579393.py", """
        class Williamsburg:
            def __init__(self42828936, Metropolitan, * Morgan, ** Bogart):
                pass
    """)
    writetext(tmp.dir/"p", """
        from f20579393 import Williamsburg
    """,
    )
    output, retcode = py(
        "Williamsburg??", PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.dir / "p"
    )
    assert retcode == 0
    assert ">>> Williamsburg(Metropolitan, *Morgan, **Bogart)" in output


def test_help_class_new_1(tmp):
    writetext(tmp.dir/"f56365338.py", """
        class Knickerbocker(object):
            def __init__(cls15515092, Wilson, * Madison, ** Linden):
                pass
    """)
    writetext(tmp.dir/"p", """
        from f56365338 import Knickerbocker
    """,
    )
    output, retcode = py(
        "?Knickerbocker", PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.dir / "p"
    )
    assert retcode == 0
    assert ">>> Knickerbocker(Wilson, *Madison, **Linden)" in output


@pytest.mark.parametrize("cmdline", [
    "b64encode --help",
    "b64encode -help",
    "b64encode --h",
    "b64encode -h",
    "b64encode --?",
    "b64encode -?",
    "b64encode ?",
    "--help b64encode",
    "-help b64encode",
    "help b64encode",
    "--h b64encode",
    "-h b64encode",
    "--? b64encode",
    "-? b64encode",
    "? b64encode",
    "b64encode?",
    "?b64encode",
    "base64.b64encode --help",
    "base64.b64encode -help",
    "base64.b64encode --h",
    "base64.b64encode -h",
    "base64.b64encode --?",
    "base64.b64encode -?",
    "base64.b64encode ?",
    "--help base64.b64encode",
    "-help base64.b64encode",
    "help base64.b64encode",
    "--? base64.b64encode",
    "-? base64.b64encode",
    "? base64.b64encode",
    "base64.b64encode?",
    "?base64.b64encode",
])
def test_function_help_variants_1(cmdline):
    output, retcode = py(cmdline.split())
    assert retcode == 0
    assert "s [altchars]" in output
    assert "--version" not in output
    assert "binascii.b2a_base64" not in output


def test_function_source_1():
    output, retcode = py("base64.b64encode", "--source")
    assert retcode == 0
    assert "[PYFLYBY] import base64" in output
    assert ">>> base64.b64encode(s, altchars=None)" in output
    assert "$ py base64.b64encode s [altchars]" in output
    assert "$ py base64.b64encode --s=... [--altchars=...]" in output
    assert "binascii.b2a_base64" in output # from source code
    assert output.count("Encode the bytes-like object s using Base64 and return a bytes object.") == 1
    assert "--version" not in output


def test_function_source_autoimport_1():
    output, retcode = py("b64encode", "--source")
    assert retcode == 0
    assert "[PYFLYBY] from base64 import b64encode" in output
    assert ">>> b64encode(s, altchars=None)" in output
    assert "$ py b64encode s [altchars]" in output
    assert "$ py b64encode --s=... [--altchars=...]" in output
    assert "binascii.b2a_base64" in output # from source code
    assert output.count("Encode the bytes-like object s using Base64 and return a bytes object.") == 1


@pytest.mark.parametrize("cmdline", [
    "b64encode --source",
    "b64encode -source",
    "b64encode --??",
    "b64encode -??",
    "b64encode ??",
    "--source b64encode",
    "-source b64encode",
    "source b64encode",
    "--?? b64encode",
    "-?? b64encode",
    "?? b64encode",
    "b64encode??",
    "??b64encode",
    "base64.b64encode --source",
    "base64.b64encode -source",
    "base64.b64encode --??",
    "base64.b64encode -??",
    "base64.b64encode ??",
    "--source base64.b64encode",
    "-source base64.b64encode",
    "source base64.b64encode",
    "--?? base64.b64encode",
    "-?? base64.b64encode",
    "?? base64.b64encode",
    "base64.b64encode??",
    "??base64.b64encode"
])
def test_function_source_variants_1(cmdline):
    output, retcode = py(cmdline.split())
    assert retcode == 0
    assert "s [altchars]" in output
    assert "binascii.b2a_base64" in output


def test_module_help_1():
    output, retcode = py("base64?")
    assert retcode == 0
    assert "RFC 3548" in output
    assert "import binascii" not in output


@pytest.mark.parametrize("args", [
    "base64 --help",
    "base64 -help",
    "base64 --h",
    "base64 -h",
    "base64 --?",
    "base64 -?",
    "base64 ?",
    "--help base64",
    "-help base64",
    "help base64",
    "--h base64",
    "-h base64",
    "--? base64",
    "-? base64",
    "? base64",
    "base64?",
    "?base64",
])
def test_module_help_variants_1(args):
    output, retcode = py(args.split())
    assert retcode == 0
    assert "RFC 3548" in output, output
    assert "import binascii" not in output


def test_module_source_1():
    output, retcode = py("base64??")
    assert retcode == 0
    assert "RFC 3548" in output
    assert "import binascii" in output


def test_module_no_help_1():
    output, retcode = py("-m", "base64", "--help")
    assert retcode == 2
    assert "option --help not recognized" in output
    assert "RFC 3548" not in output


@pytest.mark.parametrize("args", [
    "base64 --source",
    "base64 -source",
    "base64 --??",
    "base64 -??",
    "base64 ??",
    "--source base64",
    "-source base64",
    "source base64",
    "--?? base64",
    "-?? base64",
    "?? base64",
    "base64??",
    "??base64",
])
def test_module_source_variants_1(args):
    output, retcode = py(args.split())
    assert retcode == 0
    assert "RFC 3548" in output
    assert "import binascii" in output


@pytest.mark.parametrize("args", [
    "--help=3",
    "-help=3",
    "--help 3",
    "-help 3",
    "--hel=3",
    "-hel=3",
    "--hel 3",
    "-hel 3",
    "--he=3",
    "-he=3",
    "--he 3",
    "-he 3",
    "--h=3",
    "-h=3",
    "--h 3",
    "-h 3",
])
def test_function_arg_help_1(args):
    result, retcode = py("lambda help: help*4", *(args.split()))
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] lambda help: help*4
        [PYFLYBY] (lambda help: help*4)(3)
        12
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--hello=3",
    "-hello=3",
    "--hello 3",
    "-hello 3",
    "--hel=3",
    "-hel=3",
    "--hel 3",
    "-hel 3",
    "--he=3",
    "-he=3",
    "--he 3",
    "-he 3",
    "--h=3",
    "-h=3",
    "--h 3",
    "-h 3",
])
def test_function_arg_hello_1(args):
    result, retcode = py("lambda hello: hello*7", *(args.split()))
    assert retcode == 0
    expected = dedent(
        """
        [PYFLYBY] lambda hello: hello*7
        [PYFLYBY] (lambda hello: hello*7)(3)
        21
    """).strip()
    assert result == expected


def test_function_arg_help_qmark_1():
    output, retcode = py("lambda help: help*4", "-?")
    assert retcode == 0
    assert "$ py 'lambda help: help*4' help" in output


def test_function_arg_help_help_1():
    output, retcode = py('lambda help: help*4', '--help')
    assert retcode == 1
    assert "Missing argument to --help" in output


def test_function_arg_help_h_1():
    output, retcode = py('lambda help: help*4', '-h')
    assert retcode == 1
    assert "Missing argument to -h" in output


def test_object_method_help_1():
    output, retcode = py("email.message.Message().get", "--help")
    assert retcode == 0
    assert "$ py 'email.message.Message().get' name [failobj]" in output
    assert "Get a header value." in output


@pytest.mark.parametrize("args", [
    "email.message.Message().get --help",
    "email.message.Message().get -help",
    "email.message.Message().get --h",
    "email.message.Message().get -h",
    "email.message.Message().get --?",
    "email.message.Message().get -?",
    "email.message.Message().get ?",
    "email.message.Message().get?",
    "--help email.message.Message().get",
    "-help email.message.Message().get",
    "help email.message.Message().get",
    "--h email.message.Message().get",
    "-h email.message.Message().get",
    "--? email.message.Message().get",
    "-? email.message.Message().get",
    "? email.message.Message().get",
    "?email.message.Message().get",
])
def test_object_method_help_variants_1(args):
    output, retcode = py(args.split())
    assert retcode == 0
    assert "$ py 'email.message.Message().get' name [failobj]" in output
    assert "Get a header value." in output


def test_object_method_source_1():
    output, retcode = py('email.message.Message().get', '--source')
    assert retcode == 0
    assert "$ py 'email.message.Message().get' name [failobj]" in output
    assert "Get a header value." in output
    assert "name.lower()" in output


@pytest.mark.parametrize("args", [
    "email.message.Message().get --source",
    "email.message.Message().get -source",
    "email.message.Message().get --??",
    "email.message.Message().get -??",
    "email.message.Message().get ??",
    "email.message.Message().get??",
    "--source email.message.Message().get",
    "-source email.message.Message().get",
    "source email.message.Message().get",
    "--?? email.message.Message().get",
    "-?? email.message.Message().get",
    "?? email.message.Message().get",
    "??email.message.Message().get",
])
def test_object_method_source_variants1(args):
    output, retcode = py(args.split())
    assert retcode == 0
    assert "$ py 'email.message.Message().get' name [failobj]" in output
    assert "Get a header value." in output
    assert "name.lower()" in output


def test_arg_nodashdash_1():
    result, retcode = py('print', '42.0000', 'sys')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(42.0, <module 'sys' (built-in)>)
        42.0 <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_arg_dashdash_1():
    result, retcode = py('print', '--', '42.0000', 'sys')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('42.0000', 'sys')
    42.0000 sys
    """).strip()
    assert result == expected


def test_arg_dashdash_2():
    result, retcode = py('print', '42.0000', '--', 'sys')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(42.0, 'sys')
    42.0 sys
    """).strip()
    assert result == expected


def test_arg_dashdash_3():
    result, retcode = py('print', '42.0000', 'sys', '--')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(42.0, <module 'sys' (built-in)>)
        42.0 <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_arg_dashdash_4():
    result, retcode = py('print', '42.0000', 'sys', '--', '--')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(42.0, <module 'sys' (built-in)>, '--')
        42.0 <module 'sys' (built-in)> --
    """).strip()
    assert result == expected


def test_arg_dashdash_help_1():
    result, retcode = py('print', '--', '--help')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('--help')
        --help
    """).strip()
    assert result == expected


def test_arg_dashdash_dashdash_1():
    result, retcode = py('print', '--', '--', '42.000')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('--', '42.000')
        -- 42.000
    """).strip()
    assert result == expected


def test_kwargs_no_dashdash_1():
    result, retcode = py("lambda *a,**k: (a,k)", "3.500", "--foo", "7.500")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] lambda *a,**k: (a,k)
        [PYFLYBY] (lambda *a,**k: (a,k))(3.5, foo=7.5)
        ((3.5,), {'foo': 7.5})
    """).strip()
    assert result == expected, result


def test_kwargs_dashdash_1():
    result, retcode = py("lambda *a,**k: (a,k)", "--", "3.500", "--foo", "7.500")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] lambda *a,**k: (a,k)
        [PYFLYBY] (lambda *a,**k: (a,k))('3.500', '--foo', '7.500')
        (('3.500', '--foo', '7.500'), {})
    """).strip()
    assert result == expected


def test_joinstr_1():
    result, retcode = py("3", "+", "5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] 3 + 5
        8
    """).strip()
    assert result == expected


def test_print_joinstr_1():
    result, retcode = py("print", "3", "+", "5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(3, '+', 5)
        3 + 5
    """).strip()
    assert result == expected

def test_print_joinstr_2():
    result, retcode = py("print", "3 + 5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print(8)
        8
    """).strip()
    assert result == expected


def test_join_single_arg_1():
    result, retcode = py("print", "sys")
    assert retcode == 0
    # In autocall mode, the arguments are evaluated and the repr() is
    # printed for the [PYFLYBY] line
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(<module 'sys' (built-in)>)
        <module 'sys' (built-in)>
    """).strip()

    assert result == expected


def test_join_single_arg_fallback_1():
    # Verify that when heuristically joining, we fall back to heuristic apply.
    # Even though "print foo" is parsable as a joined string, if ``foo`` is not
    # importable, then fallback to "print('foo')".
    result, retcode = py("print", "ardmore23653526")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('ardmore23653526')
        ardmore23653526
    """).strip()
    assert result == expected


def test_no_ipython_for_eval_1():
    result, retcode = py("-q", "'os' in sys.modules, 'IPython' in sys.modules")
    assert retcode == 0
    expected = "(True, False)"
    assert result == expected


def test_outputmode_interactive_pprint_1():
    result, retcode = py('dict(zip("abcdefghij","ABCDEFGHIJ"))')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] dict(zip("abcdefghij","ABCDEFGHIJ"))
        {'a': 'A',
         'b': 'B',
         'c': 'C',
         'd': 'D',
         'e': 'E',
         'f': 'F',
         'g': 'G',
         'h': 'H',
         'i': 'I',
         'j': 'J'}
    """).strip()
    assert result == expected


def test_outputmode_interactive_pprint_str_1():
    result, retcode = py('--output=interactive', '"Grove"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Grove"
        'Grove'
    """).strip()
    assert result == expected


def test_outputmode_interactive_none_1():
    result, retcode = py('--output=interactive', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=inTeraCtive",
    "--output iNteracTive",
    "--output i",
    "--output_mode=I",
    "--output-mode=i",
    "--outmode i",
    "--out i",
    "-out I",
    "-o i",
    "-o=i",
    "--o i",
])
def test_outputmode_interactive_variants_1(args):
    result, retcode = py((args + ' "Perry"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Perry"
        'Perry'
    """).strip()
    assert result == expected
    result, retcode = py((args + " None").split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected


def test_outputmode_str_1():
    result, retcode = py('--output=str', '"Morton"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Morton"
        Morton
    """).strip()
    assert result == expected


def test_outputmode_str_date_1():
    result, retcode = py('--output=str', 'datetime.date(2014,7,18)')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import datetime
        [PYFLYBY] datetime.date(2014,7,18)
        2014-07-18
    """).strip()
    assert result == expected


def test_outputmode_str_none_1():
    result, retcode = py('--output=str', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
        None
    """).strip()
    assert result == expected


def test_outputmode_str_str_none_1():
    result, retcode = py('--output=str', '"None"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "None"
        None
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=StriNg",
    "--output sTr",
    "--output prInt",
    "-o p",
    "--print",
    "-print",
])
def test_outputmode_str_variants_1(args):
    result, retcode = py((args + ' "Greene"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Greene"
        Greene
    """).strip()
    assert result == expected


def test_outputmode_silent_1():
    result, retcode = py('--output=silent', '"Bethune"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Bethune"
    """).strip()
    assert result == expected


def test_outputmode_silent_outputonly_1():
    result, retcode = py('--output=silent', 'sys.stdout.write("Gansevoort"), 78844525')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write("Gansevoort"), 78844525
        Gansevoort
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=nO",
    "--output NoNe",
    "--output n",
    "-o SilEnt",
    "--silent",
    "-silent",
])
def test_outputmode_silent_variants_1(args):
    result, retcode = py((args + ' "Clarkson"').split())
    assert retcode == 0
    expected = '[PYFLYBY] "Clarkson"'
    assert result == expected


def test_outputmode_repr_str_1():
    result, retcode = py('--output=repr', '"Moore"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Moore"
        'Moore'
    """).strip()
    assert result == expected


def test_outputmode_repr_date_1():
    result, retcode = py('--output=repr', 'datetime.date(2014,7,18)')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import datetime
        [PYFLYBY] datetime.date(2014,7,18)
        datetime.date(2014, 7, 18)
    """).strip()
    assert result == expected


def test_outputmode_repr_none_1():
    result, retcode = py('--output=repr', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
        None
    """).strip()
    assert result == expected


def test_outputmode_repr_str_none_1():
    result, retcode = py('--output=repr', '"None"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "None"
        'None'
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=Repr",
    "--output repR",
    "--output r",
    "-o r",
    "--repr",
    "-repr",
])
def test_outputmode_repr_variants_1(args):
    result, retcode = py((args + ' "Norfolk"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Norfolk"
        'Norfolk'
    """).strip()
    assert result == expected
    result, retcode = py((args + ' None').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
        None
    """).strip()
    assert result == expected


def test_outputmode_reprifnotnone_date_1():
    result, retcode = py('--output=repr-if-not-none', 'datetime.date(2014,7,18)')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import datetime
        [PYFLYBY] datetime.date(2014,7,18)
        datetime.date(2014, 7, 18)
    """).strip()
    assert result == expected


def test_outputmode_reprifnotnone_none_1():
    result, retcode = py('--output=repr-if-not-none', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=REPR-if-NOT-none",
    "--output reprifnotnone",
    "--output reprunlessnone",
    "-o rn",
])
def test_outputmode_reprifnotnone_variants_1(args):
    result, retcode = py((args + ' "Suffolk"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Suffolk"
        'Suffolk'
    """).strip()
    assert result == expected
    result, retcode = py((args + ' None').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected


def test_outputmode_pprint_1():
    result, retcode = py('--output=pprint', 'dict(zip("abcdefghij","ABCDEFGHIJ"))')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] dict(zip("abcdefghij","ABCDEFGHIJ"))
        {'a': 'A',
         'b': 'B',
         'c': 'C',
         'd': 'D',
         'e': 'E',
         'f': 'F',
         'g': 'G',
         'h': 'H',
         'i': 'I',
         'j': 'J'}
    """).strip()
    assert result == expected


def test_outputmode_pprint_str_1():
    result, retcode = py('--output=pprint', '"Willett"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Willett"
        'Willett'
    """).strip()
    assert result == expected


def test_outputmode_pprint_none_1():
    result, retcode = py('--output=pprint', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
        None
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=pPrInT",
    "--output pprint",
    "--output pp",
    "-o PP",
    "--pprint",
    "-pprint",
])
def test_outputmode_pprint_variants_1(args):
    result, retcode = py((args + ' "Delancey"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Delancey"
        'Delancey'
    """).strip()
    assert result == expected
    result, retcode = py((args + ' None').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
        None
    """).strip()
    assert result == expected
    result, retcode = py((args + ' dict(zip("abcdefghij","ABCDEFGHIJ"))').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] dict(zip("abcdefghij","ABCDEFGHIJ"))
        {'a': 'A',
         'b': 'B',
         'c': 'C',
         'd': 'D',
         'e': 'E',
         'f': 'F',
         'g': 'G',
         'h': 'H',
         'i': 'I',
         'j': 'J'}
    """).strip()
    assert result == expected


def test_outputmode_pprintifnotnone_1():
    result, retcode = py('--output=pprint-if-not-none', '"Baruch"')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Baruch"
        'Baruch'
    """).strip()
    assert result == expected


def test_outputmode_pprintifnotnone_none_1():
    result, retcode = py('--output=pprint-if-not-none', 'None')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected
    result, retcode = py('--quiet', '--output=pprint-if-not-none', 'None')
    assert retcode == 0
    assert "" == result


@pytest.mark.parametrize("args", [
    "--output=pprint-if-not-none",
    "--output PprintIfNotNone",
    "--output pprintUNLESSnone",
    "-o ppn",
])
def test_outputmode_pprintifnotnone_variants_1(args):
    result, retcode = py((args + ' "Rivington"').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] "Rivington"
        'Rivington'
    """).strip()
    assert result == expected
    result, retcode = py((args + ' None').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] None
    """).strip()
    assert result == expected
    result, retcode = py((args + ' dict(zip("abcdefghij","ABCDEFGHIJ"))').split())
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] dict(zip("abcdefghij","ABCDEFGHIJ"))
        {'a': 'A',
         'b': 'B',
         'c': 'C',
         'd': 'D',
         'e': 'E',
         'f': 'F',
         'g': 'G',
         'h': 'H',
         'i': 'I',
         'j': 'J'}
    """).strip()
    assert result == expected


def test_outputmode_bad_1():
    result, retcode = py("--output=foo81576743", "5")
    assert retcode == 1
    assert "Invalid output='foo81576743'" in result


def test_run_module_1():
    result, retcode = py("-m", "base64", "-d", "-", stdin=b"VHJpbml0eQ==")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m base64 -d -
        Trinity
    """).strip()
    assert result == expected


@pytest.mark.parametrize("args", [
    "--module base64",
    "-module base64",
    "module base64",
    "--m base64",
    "-m base64",
    "-mbase64",
])
def test_run_module_variants_1(args):
    result, retcode = py((args + " -d -").split(), stdin=b"VHJvdXRtYW4=")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m base64 -d -
        Troutman
    """).strip()
    assert result == expected


def test_run_module_argstr_1(tmp):
    # runmodule.  Verify that arguments are strings and not evaluated, and
    # verify that argv works correctly.
    writetext(tmp.dir/"odule12786636.py", """
        from __future__ import print_function
        if __name__ == "__main__":
            import sys
            print("Rector", sys.argv)
    """)
    result, retcode = py("-module12786636", "22524739.000", "math",
                PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m odule12786636 22524739.000 math
        Rector ['%s/odule12786636.py', '22524739.000', 'math']
    """).strip() % tmp.dir
    assert result == expected


def test_run_module_under_package_1(tmp):
    result, retcode = py("encodings.rot_13", stdin=b"Tenavgr")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import encodings
        [PYFLYBY] python -m encodings.rot_13
        Granite
    """).strip()
    assert result == expected


def test_heuristic_run_module_1():
    result, retcode = py("base64", "-d", "-", stdin=b"U2VuZWNh")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m base64 -d -
        Seneca
    """).strip()
    assert result == expected


def test_heuristic_run_module_under_package_1(tmp):
    result, retcode = py("encodings.rot_13", stdin=b"Qrpxre")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import encodings
        [PYFLYBY] python -m encodings.rot_13
        Decker
    """).strip()
    assert result == expected


def test_heuristic_run_module_under_package_2(tmp):
    os.mkdir("%s/bard22402805" % tmp.dir)
    os.mkdir("%s/bard22402805/douglas" % tmp.dir)
    writetext(tmp.dir/"bard22402805/__init__.py", """
        from __future__ import print_function
        print('Davis', __name__)
    """)
    writetext(tmp.dir/"bard22402805/douglas/__init__.py", """
        from __future__ import print_function
        print('Clove', __name__)
    """)
    writetext(tmp.dir/"bard22402805/douglas/thames.py", """
        from __future__ import print_function
        print('Huron', __name__)
    """)
    result, retcode = py("bard22402805.douglas.thames", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import bard22402805
        Davis bard22402805
        [PYFLYBY] import bard22402805.douglas
        Clove bard22402805.douglas
        [PYFLYBY] python -m bard22402805.douglas.thames
        Huron __main__
    """).strip()
    assert result == expected


def test_heuristic_run_module_no_auto_import_1(tmp):
    # Heuristic runmodule.  Verify that we don't auto-import anything.
    writetext(tmp.dir/"vernon84909775.py", """
        if __name__ == "__main__":
            print('Basin')
            os # expect NameError
    """)
    result, retcode = py("vernon84909775", PYTHONPATH=tmp.dir)
    assert retcode == 1
    assert "Basin" in result
    assert "NameError: name 'os' is not defined" in result


def test_heuristic_run_module_nameerror_1(tmp):
    # Heuristic runmodule.  Verify that NameError in module doesn't confuse us.
    writetext(tmp.dir/"blaine15479940.py", """
        glenwood75406634
    """)
    result, retcode = py("blaine15479940", PYTHONPATH=tmp.dir)
    assert retcode == 1
    assert result.endswith("NameError: name 'glenwood75406634' is not defined")


def test_heuristic_run_module_importerror_1(tmp):
    # Heuristic runmodule.  Verify that ImportError in module doesn't confuse
    # us.
    writetext(tmp.dir/"griswold73262001.py", """
        import whitewood62047754
    """)
    result, retcode = py("griswold73262001", PYTHONPATH=tmp.dir)
    assert retcode == 1
    assert result.endswith("ModuleNotFoundError: No module named 'whitewood62047754'")


def test_heuristic_run_module_argstr_1(tmp):
    # Heuristic runmodule.  Verify that arguments are strings and not
    # evaluated, and verify that argv works correctly.
    writetext(tmp.dir/"gantry20720070.py", """
        from __future__ import print_function
        if __name__ == "__main__":
            import sys
            print("Belmont", sys.argv)
    """)
    result, retcode = py("gantry20720070", "26792622.000", "math",
                PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m gantry20720070 26792622.000 math
        Belmont ['%s/gantry20720070.py', '26792622.000', 'math']
    """).strip() % tmp.dir
    assert result == expected


def test_builtin_no_run_module_1(tmp):
    # Verify that builtins take precedence over modules.
    writetext(tmp.dir/"round.py", """
        print('bad morrison56321353')
    """)
    result, retcode = py("round", "17534159.5", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] round(17534159.5)
        17534160
    """).strip()
    assert result == expected


def test_run_module_no_superfluous_import_1(tmp):
    # Verify that 'py -m foomodule' doesn't cause a superfluous import of
    # foomodule.
    writetext(tmp.dir/"delafield47227231.py", """
        from __future__ import print_function
        print('Oakwood', __name__)
    """)
    result, retcode = py("-m", "delafield47227231", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m delafield47227231
        Oakwood __main__
    """).strip()
    assert result == expected


def test_heuristic_run_module_no_superfluous_import_1(tmp):
    # Verify that 'py foomodule' doesn't cause a superfluous import of
    # foomodule.
    writetext(tmp.dir/"pelton58495419.py", """
        from __future__ import print_function
        print('Bement', __name__)
    """)
    result, retcode = py("pelton58495419", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m pelton58495419
        Bement __main__
    """).strip()
    assert result == expected


def test_unsafe_pyflyby_path_1(tmp):
    writetext(tmp.dir/"f62242229.py", """
        Walton = 3058692
    """)
    writetext(tmp.dir/"p", """
        from f62242229 import Walton
    """)
    result, retcode = py("Walton", PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.dir/"p")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] from f62242229 import Walton
        [PYFLYBY] Walton
        3058692
    """).strip()
    assert result == expected


def test_safe_no_pyflyby_path_1(tmp):
    writetext(tmp.dir/"f86964994.py", """
        Fordham = 85883909
    """)
    writetext(tmp.dir/"p", """
        from f86964994 import Fordham
    """)
    result, retcode = py("--safe", "Fordham",
                         PYTHONPATH=tmp.dir, PYFLYBY_PATH=tmp.dir/"p")
    assert retcode == 1
    assert "name 'Fordham' is not defined" in result


def test_safe_fully_qualified_module_1(tmp):
    writetext(tmp.dir/"f47762194.py", """
        Montefiore = 85883909
    """)
    result, retcode = py("--safe", "f47762194.Montefiore", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import f47762194
        [PYFLYBY] f47762194.Montefiore
        85883909
    """).strip()
    assert result == expected


def test_unsafe_args_1():
    result, retcode = py("type", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] type(<module 'sys' (built-in)>)
        <class 'module'>
    """).strip()
    assert result == expected


def test_safe_args_1():
    result, retcode = py("--safe", "type", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] type('sys')
        <class 'str'>
    """).strip()
    assert result == expected


def test_argmode_string_dashdash_1():
    result, retcode = py("--args=string", "print", "Beekman/", "--", "Spruce/", "--")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Beekman/', 'Spruce/', '--')
        Beekman/ Spruce/ --
    """).strip()
    assert result == expected


def test_safe_dashdash_1():
    result, retcode = py("--safe", "print", "Oliver/", "--", "Catherine/", "--")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Oliver/', 'Catherine/', '--')
        Oliver/ Catherine/ --
    """).strip()
    assert result == expected


def test_safe_no_concat_1():
    result, retcode = py("--safe", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('sys')
        sys
    """).strip()
    assert result == expected


def test_argmode_str_no_concat_1():
    result, retcode = py("--args=str", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('sys')
        sys
    """).strip()
    assert result == expected


def test_argmode_eval_no_concat_1():
    result, retcode = py("--args=eval", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(<module 'sys' (built-in)>)
        <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_argmode_auto_no_concat_1():
    result, retcode = py("--args=auto", "print", "sys")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] print(<module 'sys' (built-in)>)
        <module 'sys' (built-in)>
    """).strip()
    assert result == expected


def test_exec_stdin_print_statement_1():
    result, retcode = py(stdin=b"print('Carnegie')")
    assert retcode == 0
    expected = "Carnegie"
    assert result == expected


def test_exec_stdin_print_function_1():
    result, retcode = py(stdin=b"print('Sinai', file=sys.stdout)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        Sinai
    """).strip()
    assert result == expected


def test_exec_stdin_noresult_1():
    result, retcode = py(stdin=b"42")
    assert retcode == 0
    assert "" == result


def test_argv_stdin_noarg_1():
    result, retcode = py(stdin=b"print(sys.argv)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        ['']
    """).strip()
    assert result == expected


def test_argv_stdin_dash_1():
    result, retcode = py("-", stdin=b"print(sys.argv)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        ['-']
    """).strip()
    assert result == expected


def test_argv_stdin_dash_args_1():
    result, retcode = py("-", "sys", stdin=b"print(sys.argv)")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        ['-', 'sys']
    """).strip()
    assert result == expected


def test_map_1():
    result, retcode = py("-q", "--map", "print", "2", "4")
    assert retcode == 0
    expected = dedent("""
        2
        4
    """).strip()
    assert result == expected


def test_map_2():
    result, retcode = py("--map", "str.capitalize", "hello", "world")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] str.capitalize('hello')
        'Hello'
        [PYFLYBY] str.capitalize('world')
        'World'
    """).strip()
    assert result == expected


def test_map_3():
    result, retcode = py("--map", "float.as_integer_ratio", "2.5", "3.5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] float.as_integer_ratio(2.5)
        (5, 2)
        [PYFLYBY] float.as_integer_ratio(3.5)
        (7, 2)
    """).strip()
    assert result == expected


def test_map_eval_1():
    result, retcode = py("-q", "--map", "print", "1/2", "1/4")
    assert retcode == 0
    expected = dedent("""
        0.5
        0.25
    """).strip()
    assert result == expected


def test_map_stringarg_1():
    result, retcode = py("-q", "--args=str", "--map", "print", "1/2", "1/4")
    assert retcode == 0
    expected = dedent("""
        1/2
        1/4
    """).strip()
    assert result == expected


def test_map_safe_1():
    result, retcode = py("-q", "--safe", "--map", "print", "1/2", "1/4")
    assert retcode == 0
    expected = dedent("""
        1/2
        1/4
    """).strip()
    assert result == expected


def test_map_safe_dashdash_1():
    result, retcode = py("-q", "--safe", "--map", "print", "--", "--", "1/2", "--")
    assert retcode == 0
    expected = dedent("""
        --
        1/2
        --
    """).strip()
    assert result == expected


def test_map_dashdash_1():
    result, retcode = py("-q", "--map", "print", "--", "1/2", "1/4")
    assert retcode == 0
    expected = dedent("""
        1/2
        1/4
    """).strip()
    assert result == expected


def test_map_dashdash_dashdash_1():
    result, retcode = py("-q", "--map", "print", "--", "--", "1/2", "--", "1/4")
    assert retcode == 0
    expected = dedent("""
        --
        1/2
        --
        1/4
    """).strip()
    assert result == expected


def test_map_lambda_1():
    result, retcode = py("--map", "lambda x: x**2", "1", "2", "3", "4", "5")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] (lambda x: x**2)(1)
        1
        [PYFLYBY] (lambda x: x**2)(2)
        4
        [PYFLYBY] (lambda x: x**2)(3)
        9
        [PYFLYBY] (lambda x: x**2)(4)
        16
        [PYFLYBY] (lambda x: x**2)(5)
        25
    """).strip()
    assert result == expected


def test_map_empty_1():
    result, retcode = py("-q", "--map", "print")
    assert retcode == 0
    assert "" == result


def test_map_dashdash_empty_1():
    result, retcode = py("-q", "--map", "print", "--")
    assert retcode == 0
    assert "" == result


def test_map_missing_function_1():
    result, retcode = py("-q", "--map")
    assert retcode == 1
    assert "expected argument to --map" in result


def test_output_exit_1():
    result, retcode = py("--output=exit", "5+7")
    assert retcode == 12
    expected = "[PYFLYBY] 5+7"
    assert result == expected


@pytest.mark.parametrize("args", [
    "--output=exit 5+7",
    "--output=exit 5 + 7",
    "--output=eXiT 5+ 7",
    "--output=systemEXIT 4+8",
    "--output=raise 3+8+1",
])
def test_output_exit_variants_1(args):
    result, retcode = py(("-q " + args).split())
    assert retcode == 12
    expected = ""
    assert result == expected


def test_info_function_simple_1():
    result, retcode = py('--output=silent', 'sys.stdout.write', 'Franklin')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write('Franklin')
        Franklin
    """).strip()
    assert result == expected


def test_info_function_lambda_1():
    result, retcode = py('--output=silent', '(lambda: sys.stdout.write)()', 'Chambers')
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] (lambda: sys.stdout.write)()
        [PYFLYBY] (lambda: sys.stdout.write)()('Chambers')
        Chambers
    """).strip()
    assert result == expected


def test_name_eval_1():
    result, retcode = py("-c", "__name__")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] __name__
        '__main__'
    """).strip()
    assert result == expected


def test_name_heuristic_eval_1():
    result, retcode = py("__name__")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] __name__
        '__main__'
    """).strip()
    assert result == expected


def test_name_heuristic_apply_eval_1():
    result, retcode = py("--output=silent", "sys.stdout.write", "__name__")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write('__main__')
        __main__
    """).strip()
    assert result == expected


def test_name_heuristic_join_eval_1():
    result, retcode = py("print", "'Castle'", ",", "__name__")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] print('Castle', ',', '__main__')
        Castle , __main__
    """).strip()
    assert result == expected


def test_name_stdin_1():
    result, retcode = py(stdin=b"print(('Winter', __name__))")
    assert retcode == 0
    expected = dedent("""
        ('Winter', '__main__')
    """).strip()
    assert result == expected


def test_name_dash_stdin_1():
    result, retcode = py("-", stdin=b"print(('Victory', __name__))")
    assert retcode == 0
    expected = dedent("""
        ('Victory', '__main__')
    """).strip()
    assert result == expected


def test_name_file_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write('from __future__ import print_function\nprint("Forest", __name__)\n')
        f.flush()
        result, retcode = py("--file", f.name)
        assert retcode == 0
    expected = dedent("""
        Forest __main__
    """).strip()
    assert result == expected


def test_name_heuristic_file_1():
    with tempfile.NamedTemporaryFile(suffix=".py", mode='w+') as f:
        f.write('from __future__ import print_function\nprint("Oakland", __name__)\n')
        f.flush()
        result, retcode = py(f.name)
        assert retcode == 0
    expected = dedent("""
        Oakland __main__
    """).strip()
    assert result == expected


def test_name_module_1(tmp):
    # Verify that 'py -m modulename' works.  Also verify that we don't import the
    # module by name before run_module.
    writetext(tmp.dir/"swan80274886.py", """
        from __future__ import print_function
        print('Lafayette', __name__)
    """)
    result, retcode = py("-m", "swan80274886", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m swan80274886
        Lafayette __main__
    """).strip()
    assert result == expected


def test_name_heuristic_module_1(tmp):
    # Verify that 'py modulename' works.  Also verify that we don't import the
    # module by name before run_module.
    writetext(tmp.dir/"arnold17339681.py", """
        from __future__ import print_function
        print('Hendricks', __name__)
    """)
    result, retcode = py("arnold17339681", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m arnold17339681
        Hendricks __main__
    """).strip()
    assert result == expected


def test_unknown_option_1():
    result, retcode = py("--Charlotte", "--module", "profile")
    assert retcode == 1
    assert "[PYFLYBY] Unknown option --Charlotte" in result
    assert "For usage, see:" in result


@pytest.mark.parametrize("args", flatten([
    "--tremont", "--Elsmere", "-Mohegan",
    [ ["--%s"%x, "-%s"%x] for x in "abgjklnprstuvwxyz"],
    [ ["--%s"%x, "-%s"%x] for x in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
]))
def test_unknown_option_variants_1(args):
    result, retcode = py(args.split())
    assert retcode == 1
    assert "[PYFLYBY] Unknown option "+args.split()[0] in result
    assert "For usage, see:" in result


@pytest.mark.parametrize("m", list(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"))
def test_single_char_arg0_1(tmp, m):
    # Verify that single characters without dashes aren't treated as options,
    # i.e. verify that we don't treat e.g. "py c 42" as "py -c 42".
    writetext(tmp.dir/("%s.py"%m), """
        from __future__ import print_function
        import sys
        print('Hayward', sys.argv[1])
    """)
    result, retcode = py(m, "42", PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] python -m %s 42
        Hayward 42
    """).strip() % m
    assert result == expected


def test_auto_arg_goodname_1():
    result, retcode = py("--output=silent", "sys.stdout.write", "os.path.sep")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] import os.path
        [PYFLYBY] sys.stdout.write('/')
        /
    """).strip()
    assert result == expected


def test_auto_arg_badname_1():
    result, retcode = py("--output=silent", "sys.stdout.write", "Burnside55731946.Valentine")
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] sys.stdout.write('Burnside55731946.Valentine')
        Burnside55731946.Valentine
    """).strip()
    assert result == expected


def test_auto_arg_goodname_property_1(tmp):
    writetext(tmp.dir/"quarry47946518.py", """
        class Creston(object):
            @property
            def sedgwick(self):
                return 'arden'
        creston = Creston()
    """)
    result, retcode = py("--output=silent", "sys.stdout.write", "quarry47946518.creston.sedgwick",
                PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import sys
        [PYFLYBY] import quarry47946518
        [PYFLYBY] sys.stdout.write('arden')
        arden
    """).strip()
    assert result == expected


def test_auto_arg_broken_name_property_1(tmp):
    # Verify that a NameError in user code doesn't confuse us into
    # using an argument as a string.
    writetext(tmp.dir/"kingsbridge90850275.py", """
        class Mosholu(object):
            @property
            def cortlandt(self):
                return Woodlawn # bad
        mosholu = Mosholu()
    """)
    result, retcode = py(
        "sys.stdout.write", "kingsbridge90850275.mosholu.cortlandt",
        PYTHONPATH=tmp.dir)
    assert retcode == 1
    assert "[PYFLYBY] import kingsbridge90850275\n" in result
    assert "NameError: name 'Woodlawn' is not defined" in result


@pytest.mark.xfail # TODO FIXME
def test_auto_arg_broken_import_1(tmp):
    # Verify that an ImportError in user code doesn't confuse us into
    # using an argument as a string.
    writetext(tmp.dir/"mclean76253083.py", """
        import martha8602542
    """)
    result, retcode = py(
        "sys.stdout.write", "mclean76253083.winfred",
        PYTHONPATH=tmp.dir)
    assert retcode == 1
    assert "[PYFLYBY] import mclean76253083\n" in result
    assert "ImportError:XXX" in result


def test_first_arg_empty_string_1():
    result, retcode = py("", "5")
    assert retcode == 1
    assert "got empty string as first argument" in result


def test_first_arg_spaces_1():
    result, retcode = py("\t  \t ", "5")
    assert retcode == 1
    assert "got empty string as first argument" in result


def test_function_defaults_1(tmp):
    # Verify that default values get passed through without being disturbed,
    # without being round-tripped through strings, etc.
    writetext(tmp.dir / "dobbin69118865.py", """
        from __future__ import print_function

        class X(object):
            _ctr = 0
            def __init__(self):
                X._ctr += 1
                self._i = X._ctr
            def __repr__(self):
                return "<X %d>" % (self._i)
            def __str__(self):
                return "<<X %d>>" % (self._i)
        def meserole(a, b, c=X(), d="77610270.000", e=None, f=X()):
            print(a, b, c, d, e, f)
    """)
    result, retcode = py("dobbin69118865.meserole", "java", "'kent'", "--e=paidge",
                PYTHONPATH=tmp.dir)
    assert retcode == 0
    expected = dedent("""
        [PYFLYBY] import dobbin69118865
        [PYFLYBY] dobbin69118865.meserole('java', 'kent', c=<X 1>, d='77610270.000', e='paidge', f=<X 2>)
        java kent <<X 1>> 77610270.000 paidge <<X 2>>
    """).strip()
    assert result == expected


def test_apply_not_a_function():
    result, retcode = py("--call", "75650517")
    assert retcode == 1
    assert "NotAFunctionError: ('Not a function', 75650517)" in result


def test_virtualenv_recognized(tmpdir, monkeypatch):
    """Verify that virtualenv sys.path is set correctly, and that warnings are emitted."""
    if os.environ.get("VIRTUAL_ENV") is not None:
        old_path = os.environ["PATH"].split(os.pathsep)
        new_path = os.pathsep.join(old_path[1:])

        monkeypatch.delenv("VIRTUAL_ENV")
        monkeypatch.setenv("PATH", new_path)

    no_venv_stdout, retcode = py('print(sys.path)')
    assert retcode == 0
    no_venv_sys_path = ast.literal_eval(no_venv_stdout.split('\n')[-1])

    env_dir = os.path.join(tmpdir, "venv")
    env_bin = os.path.join(env_dir, "Scripts" if os.name == "nt" else "bin")
    venv.create(env_dir)

    # Simulate activation
    monkeypatch.setenv("VIRTUAL_ENV", env_dir)
    monkeypatch.setenv("PATH", env_bin + os.pathsep + os.environ["PATH"])

    venv_stdout, retcode = py('print(sys.path)')
    assert retcode == 0
    venv_sys_path = ast.literal_eval(venv_stdout.split('\n')[-1])

    # Check that the appropriate warning is in place when using the venv,
    # and missing if not.
    warning =  (
        "UserWarning: Attempting to work in a virtualenv. "
        "If you encounter problems, please install pyflyby inside the virtualenv."
    )
    assert warning not in no_venv_stdout
    assert warning in venv_stdout

    # Check that sys.path printed from the subprocess contains the same
    # paths as what we have in the test process
    for path in sys.path:

        # If a path is missing from one, it must be missing from the other
        # (because both are called in subprocesses, which means that e.g.
        # the pyenv bin path won't be included in the subprocess call but
        # will be in the pytest call that runs this test)
        if path not in no_venv_stdout:
            assert path not in venv_stdout
        else:
            assert path in venv_stdout
            assert path in no_venv_stdout

    # Check that sys.path of the non-virtualenv appears
    # in the sys.path of the virtualenv
    #
    # Get the last line (which contains the printed sys.path); convert
    # back into a list
    assert all(path in venv_sys_path for path in no_venv_sys_path)

    # Check that the virtualenv directory appears in the sys.path of
    # the virtualenv, but not in the sys.path of the non-virtualenv
    assert not any(env_dir in path for path in no_venv_sys_path)
    assert any(env_dir in path for path in venv_sys_path)


def test_beartype_with_forward_reference_1(tmp):
    file = tmp.dir/"beartype_test.py"
    writetext(file, """
        from beartype import beartype
        from pathlib import Path

        @beartype
        def test_func(x: "Path") -> None:
            pass

        test_func(Path())
        # this may appear in traceback, so we obfuscate it
        print(base64.b64decode(b'YmVhcnR5cGVvaw=='))
    """)
    result, retcode = py(str(file))
    assert retcode == 0
    # The test should succeed and print "OK" without raising errors
    # about __main__ module not being properly set up
    assert "Forward reference" not in result
    assert "BeartypeCallHintForwardRefException" not in result
    assert "beartypeok" in result

@pytest.mark.skipif(shutil.which("gdb") is None, reason="gdb is required for this test")
@pytest.mark.skipif(sys.platform == "darwin", reason="test not applicable on macOS")
def test_inject_insufficient_permissions():
    """Test that having insufficient permissions for gdb to attach triggers an error."""
    child = subprocess.Popen(["python", "-c", "import time; time.sleep(20)"])

    with open("/proc/sys/kernel/yama/ptrace_scope") as f:
        if f.read().strip() == "0":
            pytest.skip(msg="ptrace is allowed without elevated user permissions")

    # Should fail due to permissions
    with pytest.raises(Exception):
        inject(child.pid, [])


def test_logged_list_getitem_marks_accessed():
    ll = LoggedList(["a", "b", "c"])
    assert ll[1] == "b"
    assert ll.unaccessed == ["a", "c"]


def test_logged_list_slice_marks_accessed():
    ll = LoggedList(["a", "b", "c", "d"])
    assert ll[1:3] == ["b", "c"]
    assert ll.unaccessed == ["a", "d"]


def test_logged_list_iter_marks_all_accessed():
    ll = LoggedList(["a", "b", "c"])
    list(ll)
    assert ll.unaccessed == []


def test_logged_list_len_does_not_mark():
    ll = LoggedList(["a", "b"])
    assert len(ll) == 2
    assert ll.unaccessed == ["a", "b"]


def test_logged_list_repr_marks_all():
    ll = LoggedList(["a", "b"])
    repr(ll)
    assert ll.unaccessed == []


# TODO: test timeit, time
# TODO: test --attach
# TODO: test postmortem debugging
# TODO: test SystemExit
# TODO: test SIGQUIT
# TODO: test faulthandler
# TODO: test globals e.g. breakpoint
# TODO: test py python foo
# TODO: test py program-on-$PATH
# TODO: test py --debug 'code...'
# TODO: test py --debug PID
# TODO: test repeated attach to the same PID.
# TODO: test py -i filename.pya
# TODO: test py -i 'code ...'
# TODO: test 'py -i' == 'py' (no double shell)
# TODO: exiting debugger with EOF (control-D)
