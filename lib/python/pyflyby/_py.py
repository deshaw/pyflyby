# pyflyby/_py.py
# Copyright (C) 2014, 2015, 2018, 2019 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

r"""
The `py` program (part of the pyflyby project) is a command-line multitool for
running python code, with heuristic intention guessing, automatic importing,
and debugging support.

Invocation summary
==================

.. code::

  py [--file]   filename.py arg1 arg2   Execute a file
  py [--eval]  'function(arg1, arg2)'   Evaluate an expression/statement
  py [--apply]  function arg1 arg2      Call function(arg1, arg2)
  py [--module] modname arg1 arg2       Run a module

  py  --map     function arg1 arg2      Call function(arg1); function(arg2)

  py  -i       'function(arg1, arg2)'   Run file/code/etc, then run IPython
  py  --debug  'function(arg1, arg2)'   Debug file/code/etc
  py  --debug   PID                     Attach debugger to PID

  py            function?               Get help for a function or module
  py            function??              Get source of a function or module

  py                                    Start IPython with autoimporter
  py nb                                 Start IPython Notebook with autoimporter


  py [--add-deprecated-builtins]        Inject "breakpoint", "debug_exception",
                                        "debug_statement", "waitpoint" into
                                        builtins. This is deprecated, and
                                        present for backward compatibilty
                                        but will be removed in the future.

Features
========

  * Heuristic action mode guessing: If none of --file, --eval, --apply,
    --module, or --map is specified, then guess what to do, choosing one of
    these actions:

      * Execute (run) a file
      * Evaluate concatenated arguments
      * Run a module
      * Call (apply) a function
      * Evaluate first argument

  * Automatic importing: All action modes (except run_module) automatically
    import as needed.

  * Heuristic argument evaluation: By default, `py --eval`, `py --apply`, and
    `py --map` guess whether the arguments should be interpreted as
    expressions or literal strings. A "--" by itself will designate subsequent
    args as strings.  A "-" by itself will be replaced by the contents of
    stdin as a string.

  * Merged eval/exec: Code is eval()ed or exec()ed as appropriate.

  * Result printing: By default, results are pretty-printed if not None.

  * Heuristic flags: "print" can be used as a function or a statement.

  * Matplotlib/pylab integration: show() is called if appropriate to block on
    plots.

  * Enter debugger upon unhandled exception.  (This functionality is enabled
    by default when stdout is a tty.  Use --postmortem=no to never use the
    postmortem debugger.  Use --postmortem=yes enable even if stdout is not a
    tty.  If the postmortem debugger is enabled but /dev/tty is not available,
    then if an exception occurs, py will email instructions for attaching a
    debugger.)

  * Control-\\ (SIGQUIT) enters debugger while running (and allows continuing).

  * New builtin functions such as "debugger()".

Warning
=======
`py` is intended as an interactive tool.  When writing shell aliases for
interactive use, the `--safe` option can be useful.  When writing scripts,
it's better to avoid all heuristic guessing; use regular `python -c ...`, or
better yet, a full-fledged python program (and run tidy-imports).


Options
=======

.. code::

    Global options valid before code argument:

      --args=string    Interpret all arguments as literal strings.
                       (The "--" argument also specifies remaining arguments to be
                       literal strings.)
      --args=eval      Evaluate all arguments as expressions.
      --args=auto      (Default) Heuristically guess whether to evaluate arguments
                       as literal strings or expressions.
      --output=silent  Don't print the result of evaluation.
      --output=str     Print str(result).
      --output=repr    Print repr(result).
      --output=pprint  Print pprint.pformat(result).
      --output=repr-if-not-none
                       Print repr(result), but only if result is not None.
      --output=pprint-if-not-none
                       Print pprint.pformat(result), but only if result is not None.
      --output=interactive
                       (Default) Print result.__interactive_display__() if defined,
                       else pprint if result is not None.
      --output=exit    Raise SystemExit(result).
      --safe           Equivalent to --args=strings and PYFLYBY_PATH=EMPTY.
      --quiet, --q     Log only error messages to stderr; omit info and warnings.
      --interactive, --i
                       Run an IPython shell after completion
      --debug, --d     Run the target code file etc under the debugger.  If a PID is
                       given, then instead attach a debugger to the target PID.
      --verbose        Turn on verbose messages from pyflyby.

    Pseudo-actions valid before, after, or without code argument:

      --version        Print pyflyby version or version of a module.
      --help, --h, --? Print this help or help for a function or module.
      --source, --??   Print source code for a function or module.


Examples
========

  Start IPython with pyflyby autoimporter enabled::

    $ py

  Start IPython/Jupyter Notebook with pyflyby autoimporter enabled::

    $ py nb

  Find the ASCII value of the letter "j" (apply builtin function)::

    $ py ord j
    [PYFLYBY] ord('j')
    106

  Decode a base64-encoded string (apply autoimported function)::

    $ py b64decode aGVsbG8=
    [PYFLYBY] from base64 import b64decode
    [PYFLYBY] b64decode('aGVsbG8=', altchars=None)
    b'hello'

  Find the day of the week of some date (apply function in module)::

    $ py calendar.weekday 2014 7 18
    [PYFLYBY] import calendar
    [PYFLYBY] calendar.weekday(2014, 7, 18)
    4

  Using named arguments::

    $ py calendar.weekday --day=16 --month=7 --year=2014
    [PYFLYBY] import calendar
    [PYFLYBY] calendar.weekday(2014, 7, 16)
    2

  Using short named arguments::

    $ py calendar.weekday -m 7 -d 15 -y 2014
    [PYFLYBY] import calendar
    [PYFLYBY] calendar.weekday(2014, 7, 15)
    1

  Invert a matrix (evaluate expression, with autoimporting)::

    $ py 'matrix("1 3 3; 1 4 3; 1 3 4").I'
    [PYFLYBY] from numpy import matrix
    [PYFLYBY] matrix("1 3 3; 1 4 3; 1 3 4").I
    matrix([[ 7., -3., -3.],
            [-1.,  1.,  0.],
            [-1.,  0.,  1.]])

  Plot cosine (evaluate expression, with autoimporting)::

    $ py 'plot(cos(arange(30)))'
    [PYFLYBY] from numpy import arange
    [PYFLYBY] from numpy import cos
    [PYFLYBY] from matplotlib.pyplot import plot
    [PYFLYBY] plot(cos(arange(30)))
    <plot>

  Command-line calculator (multiple arguments)::

    $ py 3 / 4
    0.75

  Command-line calculator (single arguments)::

    $ py '(5+7j) \** 12'
    (65602966976-150532462080j)

  Rationalize a decimal (apply bound method)::

    $ py 2.5.as_integer_ratio
    [PYFLYBY] 2.5.as_integer_ratio()
    (5, 2)

  Rationalize a decimal (apply unbound method)::

    $ py float.as_integer_ratio 2.5
    [PYFLYBY] float.as_integer_ratio(2.5)
    (5, 2)

  Rationalize decimals (map/apply)::

    $ py --map float.as_integer_ratio 2.5 3.5
    [PYFLYBY] float.as_integer_ratio(2.5)
    (5, 2)
    [PYFLYBY] float.as_integer_ratio(3.5)
    (7, 2)

  Square numbers (map lambda)::

    $ py --map 'lambda x: x \**2' 3 4 5
    [PYFLYBY] (lambda x: x \**2)(3)
    9
    [PYFLYBY] (lambda x: x \**2)(4)
    16
    [PYFLYBY] (lambda x: x \**2)(5)
    25

  Find length of string (using "-" for stdin)::

    $ echo hello | py len -
    [PYFLYBY] len('hello\\n')
    6

  Run stdin as code::

    $ echo 'print(sys.argv[1:])' | py - hello world
    [PYFLYBY] import sys
    ['hello', 'world']

  Run libc functions::

    $ py --quiet --output=none 'CDLL("libc.so.6").printf' %03d 7
    007

  Download web page::

    $ py --print 'requests.get(sys.argv[1]).text' http://example.com

  Get function help::

    $ py b64decode?
    [PYFLYBY] from base64 import b64decode
    Python signature::

      >> b64decode(s, altchars=None, validate=False)

    Command-line signature::

      $ py b64decode s [altchars [validate]]
      $ py b64decode --s=... [--altchars=...] [--validate=...]
    ...

  Get module help::

    $ py pandas?
    [PYFLYBY] import pandas
    Version:
      0.13.1
    Filename:
      /usr/local/lib/python2.7/site-packages/pandas/__init__.pyc
    Docstring:
      pandas - a powerful data analysis and manipulation library for Python
      ...

"""

import ast
import builtins
from   contextlib               import contextmanager
from   functools                import total_ordering
import inspect
import os
from   pathlib                  import Path
import re
from   shlex                    import quote as shquote
import sys
import types
from   types                    import FunctionType, MethodType, ModuleType
from   typing                   import Any
import warnings

from   pyflyby._autoimp         import auto_import, find_missing_imports
from   pyflyby._cmdline         import print_version_and_exit, syntax
from   pyflyby._dbg             import (add_debug_functions_to_builtins,
                                        attach_debugger, debug_statement,
                                        debugger, enable_faulthandler,
                                        enable_signal_handler_debugger,
                                        enable_sigterm_handler,
                                        remote_print_stack)
from   pyflyby._file            import Filename, UnsafeFilenameError, which
from   pyflyby._flags           import CompilerFlags
from   pyflyby._idents          import is_identifier
from   pyflyby._interactive     import (get_ipython_terminal_app_with_autoimporter,
                                        run_ipython_line_magic,
                                        start_ipython_with_autoimporter)
from   pyflyby._log             import logger
from   pyflyby._modules         import ModuleHandle
from   pyflyby._parse           import PythonBlock
from   pyflyby._util            import cmp, indent, prefixes

# TODO: add --tidy-imports, etc

# TODO: new --action="concat_eval eval apply" etc.  specifying multiple
# actions means try each of them in that order.  then --safe can exclude
# concat-eval, and users can customize which action modes are included.
# --apply would be equivalent to --action=apply.

# TODO: plug-in system.  'py foo' should attempt something that the
# user/vendor can add to the system.  leading candidate: use entry_point
# system (http://stackoverflow.com/a/774859).  other candidates: maybe use
# python namespace like pyflyby.vendor.foo or pyflyby.commands.foo or
# pyflyby.magics.foo, or maybe a config file.
# TODO: note additional features in documentation feature list

# TODO: somehow do the right thing with glob.glob vs glob, pprint.pprint vs
# pprint, etc.  Ideas:
#   - make --apply special case detect modules and take module.module
#   - enhance auto_import() to keep track of the context while finding missing imports
#   - enhance auto_import() to scan for calls after importing

# TODO: pipe help/source output (all output?) through $PYFLYBY_PAGER (default "less -FRX").

# TODO: unparse ast node for info logging
# https://hg.python.org/cpython/log/tip/Tools/parser/unparse.py

# TODO: run_module should detect if the module doesn't check __name__ and
# therefore is unlikely to be meaningful to use with run_module.

# TODO: make sure run_modules etc work correctly with modules under namespace
# packages.

# TODO: detect deeper ImportError, e.g. suppose user accesses module1; module1
# imports badmodule, which can't be imported successfully and raises
# ImportError; we should get that ImportError instead of trying other things
# or turning it into a string.  probably do this by changing the place where
# we import modules to first get the loader, then if import fails, raise a
# subclass of ImportError.

# TODO: provide a way to omit newline in output.  maybe --output=write.

# TODO: make sure 'py -c' matches behavior of 'python -c' w.r.t. sys.modules["__main__"]
# $ py -c 'x=3;import sys; print sys.modules["__main__"].__dict__["x"]'
# mimic runpy.{_TempModule,_run_code}

# TODO: refactor this module - maybe to _heuristic.py

# TODO: add --profile, --runsnake
usage = """
py --- command-line python multitool with automatic importing

$ py [--file]   filename.py arg1 arg2      Execute file
$ py [--apply]  function arg1 arg2         Call function
$ py [--eval]  'function(arg1, arg2)'      Evaluate code
$ py [--module] modname arg1 arg2          Run a module

$ py --debug    file/code... args...       Debug code
$ py --debug    PID                        Attach debugger to PID

$ py                                       IPython shell
""".strip()

# Default compiler flags (feature flags) used for all user code.  We include
# "print_function" here, but we also use auto_flags=True, which means
# print_function may be flipped off if the code contains print statements.
FLAGS = CompilerFlags(["absolute_import", "with_statement", "division",
                       "print_function"])


def _get_argspec(arg:Any) -> inspect.FullArgSpec:
    from inspect import getfullargspec as getargspec, FullArgSpec as ArgSpec
    if isinstance(arg, FunctionType):
        return getargspec(arg)
    elif isinstance(arg, MethodType):
        argspec = getargspec(arg)
        if arg.__self__ is not None:
            # For bound methods, ignore the "self" argument.
            return ArgSpec(argspec.args[1:], *argspec[1:])
        return argspec
    elif isinstance(arg, type):
        if arg.__new__ is not object.__new__:
            argspec = _get_argspec(arg.__new__)
            return ArgSpec(argspec.args[1:], *argspec[1:])
        else:
            argspec = _get_argspec(arg.__init__)
            return ArgSpec(argspec.args[1:], *argspec[1:])
    elif callable(arg):
        # Unknown, probably a built-in method.
        return ArgSpec([], "args", "kwargs", None, [], None, {})
    raise TypeError(
        "_get_argspec: unexpected %s" % (type(arg).__name__,))


def _requires_parens_as_function(function_name:str) -> bool:
    """
    Returns whether the given string of a callable would require parentheses
    around it to call it.

      >>> _requires_parens_as_function("foo.bar[4]")
      False

      >>> _requires_parens_as_function("foo+bar")
      True

      >>> _requires_parens_as_function("(foo+bar)()")
      False

      >>> _requires_parens_as_function("(foo+bar)")
      False

      >>> _requires_parens_as_function("(foo)+(bar)")
      True

    :type function_name:
      ``str``
    :rtype:
      ``bool``
    """
    # TODO: this might be obsolete if we use unparse instead of keeping original
    #     user formatting (or alternatively, unparse should use something like this).

    assert isinstance(function_name, str)

    block = PythonBlock(function_name, flags=FLAGS)
    node = block.expression_ast_node
    if not node:
        # Couldn't parse?  Just assume we do need parens for now.  Or should
        # we raise an exception here?
        return True
    body = node.body
    # Is it something that doesn't need parentheses?
    if isinstance(body, (ast.Name, ast.Attribute, ast.Call, ast.Subscript)):
        return False
    # Does it already have parentheses?
    n = str(function_name)
    if n.startswith("(") and n.endswith(")"):
        # It has parentheses, superficially.  Make sure it's not something
        # like "(foo)+(bar)".
        flags = int(FLAGS) | ast.PyCF_ONLY_AST
        try:
            tnode = compile(n[1:-1], "<unknown>", "eval", flags)
        except SyntaxError:
            return True
        if ast.dump(tnode) == ast.dump(node):
            return False
        else:
            return True
    return True


def _format_call_spec(function_name:str, obj:Any)-> str:
    # using signature() is not strictly identical
    # as it might look at __text_signature__ and/or respect possitional only
    # forward slash:
    #   >>> def foo(a, /, b)
    # whcih formatargspec did not do.
    # argspec = _get_argspec(obj)
    # old_callspect = inspect.formatargspec(*argspec)
    # assert old_callspect == callspec , f"{old_callspect} !={callspec}"
    callspec = str(inspect.signature(obj))
    if _requires_parens_as_function(function_name):
        return "(%s)%s" % (function_name, callspec)
    else:
        return "%s%s" % (function_name, callspec)




def _build_function_usage_string(function_name:str, obj:Any, prefix:str):
    argspec = _get_argspec(obj)

    usage = []
    # TODO: colorize
    usage.append("Python signature:")
    usage.append("  >"+">> " + _format_call_spec(function_name, obj))
    usage.append("")
    usage.append("Command-line signature:")
    keywords = argspec.varkw
    if not argspec.args and argspec.varargs and keywords:
        # We have no information about the arguments.  It's probably a
        # built-in where getargspec failed.
        usage.append("  $ %s%s ...\n" % (prefix, function_name))
        return "\n".join(usage)
    defaults = argspec.defaults or ()
    first_with_default = len(argspec.args) - len(defaults)
    # Show first alternative of command-line syntax.
    syntax1 = "  $ %s%s" % (prefix, shquote(function_name),)
    for i, arg in enumerate(argspec.args):
        if i >= first_with_default:
            syntax1 += " [%s" % (arg,)
        else:
            syntax1 += " %s" % (arg,)
    if argspec.varargs:
        syntax1 += " %s..." % argspec.varargs
    syntax1 += "]" * len(defaults)
    for arg in argspec.kwonlyargs:
        if argspec.kwonlydefaults and arg in argspec.kwonlydefaults:
            syntax1 += " [--%s=...]" % (arg,)
        else:
            syntax1 += " --%s=..." % (arg,)
    if keywords:
        syntax1 += " [--...]"
    usage.append(syntax1)
    # usage.append("or:")
    syntax2 = "  $ %s%s" % (prefix, shquote(function_name),)
    for i, arg in enumerate(argspec.args):
        if i >= first_with_default:
            syntax2 += " [--%s=...]" % (arg,)
        else:
            syntax2 += " --%s=..." % (arg,)
    for arg in argspec.kwonlyargs:
        if argspec.kwonlydefaults and arg in argspec.kwonlydefaults:
            syntax2 += " [--%s=...]" % (arg,)
        else:
            syntax2 += " --%s=..." % (arg,)
    if argspec.varargs:
        syntax2 += " %s..." % argspec.varargs
    if keywords:
        syntax2 += " [--...]"
    usage.append(syntax2)
    usage.append("")
    return "\n".join(usage)


class ParseError(Exception):
    pass


class _ParseInterruptedWantHelp(Exception):
    pass


class _ParseInterruptedWantSource(Exception):
    pass


class UserExpr:
    """
    An expression from user input, and its evaluated value.

    The expression can come from a string literal or other raw value, or a
    string that is evaluated as an expression, or heuristically chosen.

      >>> ns = _Namespace()

    Heuristic auto-evaluation::

      >>> UserExpr('5+2', ns, "auto").value
      7

      >>> UserExpr('5j+2', ns, "auto").value
      (2+5j)

      >>> UserExpr('base64.b64decode("SGFsbG93ZWVu")', ns, "auto").value
      [PYFLYBY] import base64
      b'Halloween'

    Returning an unparsable argument as a string::

      >>> UserExpr('Victory Loop', ns, "auto").value
      'Victory Loop'

    Returning an undefined (and not auto-importable) argument as a string::

      >>> UserExpr('Willowbrook29817621+5', ns, "auto").value
      'Willowbrook29817621+5'

    Explicit literal string::

      >>> UserExpr("2+3", ns, "raw_value").value
      '2+3'

      >>> UserExpr("'2+3'", ns, "raw_value").value
      "'2+3'"

    Other raw values::

      >>> UserExpr(sys.exit, ns, "raw_value").value
      <built-in function exit>
    """

    def __init__(self, arg, namespace, arg_mode, source=None):
        """
        Construct a new UserExpr.

        :type arg:
          ``str`` if ``arg_mode`` is "eval" or "auto"; anything if ``arg_mode``
          is "raw_value"
        :param arg:
          Input user argument.
        :type namespace:
          `_Namespace`
        :type arg_mode:
          ``str``
        :param arg_mode:
          If ``"raw_value"``, then return ``arg`` unchanged.  If ``"eval"``, then
          always evaluate ``arg``.  If ``"auto"``, then heuristically evaluate
          if appropriate.
        """
        if arg_mode == "string":
            arg_mode = "raw_value"
        self._namespace = namespace
        self._original_arg_mode = arg_mode
        self._original_arg        = arg
        if arg_mode == "raw_value":
            # self.inferred_arg_mode = "raw_value"
            # self.original_source = None
            if source is None:
                source = PythonBlock(repr(self._original_arg))
            else:
                source = PythonBlock(source)
            self.source = source
            self.value = self._original_arg
        elif arg_mode == "eval":
            if source is not None:
                raise ValueError(
                    "UserExpr(): source argument not allowed for eval")
            # self.inferred_arg_mode = "eval"
            self._original_arg_as_source = PythonBlock(arg, flags=FLAGS)
            # self.original_source = self._original_arg_as_source
        elif arg_mode == "auto":
            if source is not None:
                raise ValueError(
                    "UserExpr(): source argument not allowed for auto")
            if not isinstance(arg, str):
                raise ValueError(
                    "UserExpr(): arg must be a string if arg_mode='auto'")
            self._original_arg_as_source = PythonBlock(arg, flags=FLAGS)
        else:
            raise ValueError("UserExpr(): bad arg_mode=%r" % (arg_mode,))

    def _infer_and_evaluate(self) -> None:
        if self._original_arg_mode == "raw_value":
            pass
        elif self._original_arg_mode == "eval":
            block = self._original_arg_as_source
            if not (str(block).strip()):
                raise ValueError("empty input")
            self.value = self._namespace.auto_eval(block)
            self.source = self._original_arg_as_source #.pretty_print() # TODO
        elif self._original_arg_mode == "auto":
            block = self._original_arg_as_source
            ERROR = object()
            if not (str(block).strip()):
                value = ERROR
            elif not block.parsable_as_expression:
                value = ERROR
            else:
                try:
                    value = self._namespace.auto_eval(block)
                except UnimportableNameError:
                    value = ERROR
            if value is ERROR:
                # self.inferred_arg_mode = "raw_value"
                self.value = self._original_arg
                # self.original_source = None
                self.source = PythonBlock(repr(self.value))
            else:
                # self.inferred_arg_mode = "eval"
                self.value = value
                # self.original_source = block
                self.source = block #.pretty_print() # TODO
        else:
            raise AssertionError("internal error")
        self._infer_and_evaluate = lambda: None

    def __getattr__(self, k):
        self._infer_and_evaluate()
        return object.__getattribute__(self, k)

    def __str__(self):
        return str(self._original_arg)


def _parse_auto_apply_args(argspec, commandline_args, namespace, arg_mode="auto"):
    """
    Parse command-line arguments heuristically.  Arguments that can be
    evaluated are evaluated; otherwise they are treated as strings.

    :returns:
      ``args``, ``kwargs``
    """
    # This is implemented manually instead of using optparse or argparse.  We
    # do so because neither supports dynamic keyword arguments well.  Optparse
    # doesn't support parsing known arguments only, and argparse doesn't
    # support turning off interspersed positional arguments.
    def make_expr(arg, arg_mode=arg_mode):
        return UserExpr(arg, namespace, arg_mode)

    # Create a map from argname to default value.
    defaults = argspec.defaults or ()
    argname2default = {}
    for argname, default in zip(argspec.args[len(argspec.args)-len(defaults):],
                                defaults):
        argname2default[argname] = make_expr(default, "raw_value")
    if argspec.kwonlydefaults:
        for argname, default in argspec.kwonlydefaults.items():
            argname2default[argname] = make_expr(default, "raw_value")
    # Create a map from prefix to arguments with that prefix.  E.g. {"foo":
    # ["foobar", "foobaz"]}
    prefix2argname = {}
    for argname in argspec.args:
        for prefix in prefixes(argname):
            prefix2argname.setdefault(prefix, []).append(argname)
    for argname in argspec.kwonlyargs:
        for prefix in prefixes(argname):
            prefix2argname.setdefault(prefix, []).append(argname)
    # Enumerate over input arguments.
    got_pos_args = []
    got_keyword_args = {}
    args = list(commandline_args)
    while args:
        arg = args.pop(0)
        if arg in ["--?", "-?", "?"]:
            raise _ParseInterruptedWantHelp
        elif arg in ["--??", "-??", "??"]:
            raise _ParseInterruptedWantSource
        elif arg.startswith("-"):
            if arg == "-":
                # Read from stdin and stuff into next argument as a string.
                data = sys.stdin.read()
                got_pos_args.append(make_expr(data, "string"))
                continue
            elif arg == "--":
                # Treat remaining arguments as strings.
                got_pos_args.extend([make_expr(x, "string") for x in args])
                del args[:]
                continue
            elif arg.startswith("--"):
                argname = arg[2:]
            else:
                argname = arg[1:]
            argname, equalsign, value = argname.partition("=")
            argname = argname.replace("-", "_")
            if not is_identifier(argname):
                raise ParseError("Invalid option name %s" % (argname,))
            matched_argnames = prefix2argname.get(argname, [])
            if len(matched_argnames) == 1:
                argname, = matched_argnames
            elif len(matched_argnames) == 0:
                if equalsign == "":
                    if argname in ["help", "h"]:
                        raise _ParseInterruptedWantHelp
                    if argname in ["source"]:
                        raise _ParseInterruptedWantSource
                if not argspec.varkw:
                    raise ParseError("Unknown option name %s" %
                                     (argname,))

            elif len(matched_argnames) > 1:
                raise ParseError(
                    "Ambiguous %s: could mean one of: %s"
                    % (argname,
                       ", ".join("--%s"%s for s in matched_argnames)))
            else:
                raise AssertionError
            if not value:
                try:
                    value = args.pop(0)
                except IndexError:
                    raise ParseError("Missing argument to %s" % (arg,))
                if value.startswith("--"):
                    raise ParseError(
                        "Missing argument to %s.  "
                        "If you really want to use %r as the argument to %s, "
                        "then use %s=%s."
                        % (arg, value, arg, arg, value))
            got_keyword_args[argname] = make_expr(value)
        else:
            got_pos_args.append(make_expr(arg))

    parsed_args = []
    parsed_kwargs = {}
    for i, argname in enumerate(argspec.args):
        if i < len(got_pos_args):
            if argname in got_keyword_args:
                raise ParseError(
                    "%s specified both as positional argument (%s) "
                    "and keyword argument (%s)"
                    % (argname, got_pos_args[i], got_keyword_args[argname]))
            expr = got_pos_args[i]
        else:
            try:
                expr = got_keyword_args.pop(argname)
            except KeyError:
                try:
                    expr = argname2default[argname]
                except KeyError:
                    raise ParseError(
                        "missing required argument %s" % (argname,))
        try:
            value = expr.value
        except Exception as e:
            raise ParseError(
                "Error parsing value for --%s=%s: %s: %s"
                % (argname, expr, type(e).__name__, e))
        parsed_args.append(value)

    for argname in argspec.kwonlyargs:
        try:
            expr = got_keyword_args.pop(argname)
        except KeyError:
            try:
                expr = argname2default[argname]
            except KeyError:
                raise ParseError(
                    "missing required keyword argument %s" % (argname,))

        try:
            value = expr.value
        except Exception as e:
            raise ParseError(
                "Error parsing value for --%s=%s: %s: %s"
                % (argname, expr, type(e).__name__, e))
        parsed_kwargs[argname] = value

    if len(got_pos_args) > len(argspec.args):
        if argspec.varargs:
            for expr in got_pos_args[len(argspec.args):]:
                try:
                    value = expr.value
                except Exception as e:
                    raise ParseError(
                        "Error parsing value for *%s: %s: %s: %s"
                        % (argspec.varargs, expr, type(e).__name__, e))
                parsed_args.append(value)
        else:
            max_nargs = len(argspec.args)
            if argspec.defaults:
                expected = "%d-%d" % (max_nargs-len(argspec.defaults),max_nargs)
            else:
                expected = "%d" % (max_nargs,)
            raise ParseError(
                "Too many positional arguments.  "
                "Expected %s positional argument(s): %s.  Got %d args: %s"
                % (expected, ", ".join(argspec.args),
                   len(got_pos_args), " ".join(map(str, got_pos_args))))

    for argname, expr in sorted(got_keyword_args.items()):
        try:
            parsed_kwargs[argname] = expr.value
        except Exception as e:
            raise ParseError(
                "Error parsing value for --%s=%s: %s: %s"
                % (argname, expr, type(e).__name__, e))

    return parsed_args, parsed_kwargs


def _format_call(function_name:str, argspec, args, kwargs):
    # TODO: print original unparsed arg strings
    defaults = argspec.defaults or ()
    first_with_default = len(argspec.args) - len(defaults)
    argparts = []
    for i in range(max(len(args), len(argspec.args))):
        if i >= first_with_default and len(args) <= len(argspec.args):
            argparts.append("%s=%r" % (argspec.args[i], args[i]))
        else:
            argparts.append(repr(args[i]))
    for k, v in sorted(kwargs.items()):
        argparts.append("%s=%r" % (k, v))
    if _requires_parens_as_function(function_name):
        function_name = "(%s)" % (function_name,)
    r = "%s(%s)" % (function_name, ", ".join(argparts))
    return r


class UnimportableNameError(NameError):
    pass


class NotAFunctionError(Exception):
    pass


def _get_help(expr:UserExpr, verbosity:int=1) -> str:
    """
    Construct a help string.

    :type expr:
      `UserExpr`
    :param expr:
      Object to generate help for.
    :rtype:
      ``str``
    """
    # TODO: colorize headers
    result = ""
    obj = expr.value
    name:str = str(expr.source)
    if callable(obj):
        prefix = os.path.basename(sys.orig_argv[0]) + " "
        result += _build_function_usage_string(name, obj, prefix)
    if verbosity == 0:
        include_filename = False
        include_doc      = False
        include_source   = False
    elif verbosity == 1:
        include_filename = True
        include_doc      = True
        include_source   = False
    elif verbosity == 2:
        include_filename = True
        include_doc      = False
        include_source   = True
    else:
        raise ValueError("invalid verbosity=%r" % (verbosity,))
    try:
        version = obj.__version__
    except Exception:
        pass
    else:
        result += "\nVersion:\n  %s\n" % (version,)
    if include_filename:
        try:
            filename = inspect.getfile(obj)
        except Exception:
            pass
        else:
            result += "\nFilename:\n  %s\n" % (filename,)
    if include_source:
        try:
            source = inspect.getsource(obj)
        except Exception:
            source = ""
        if source:
            # TODO: colorize source
            result += "\nSource:\n%s\n" % (indent(source, "  "))
        else:
            source = "(Not available)"
            include_doc = True
    if include_doc:
        doc = (inspect.getdoc(obj) or "").strip() or "(No docstring)"
        result += "\nDocstring:\n%s" % (indent(doc, "  "))
    return result


_enable_postmortem_debugger = None

def _handle_user_exception(exc_info=None):
    """
    Handle an exception in user code.
    """
    # TODO: Make tracebacks show user code being executed.  IPython does that
    # by stuffing linecache.cache, and also advising linecache.checkcache.  We
    # can either advise it ourselves also, or re-use IPython.core.compilerop.
    # Probably better to advise ourselves.  Add "<pyflyby-input-md5[:12]>" to
    # linecache.  Perhaps do it in a context manager that removes from
    # linecache when done.  Advise checkcache to protect any "<pyflyby-*>".
    # Do it for all code compiled from here, including args, debug_statement,
    # etc.
    if exc_info is None:
        exc_info = sys.exc_info()
    if exc_info[2].tb_next:
        exc_info = (exc_info[0], exc_info[1],
                    exc_info[2].tb_next) # skip this traceback
    # If ``_enable_postmortem_debugger`` is enabled, then debug the exception.
    # By default, this is enabled run running in a tty.
    # We check isatty(1) here because we want 'py ... | cat' to never go into
    # the debugger.  Note that debugger() also checks whether /dev/tty is
    # usable (and if not, waits for attach).
    if _enable_postmortem_debugger:
        # *** Run debugger. ***
        debugger(exc_info)
    # TODO: consider using print_verbose_tb(*exc_info)
    import traceback
    traceback.print_exception(*exc_info)
    raise SystemExit(1)


def auto_apply(function, commandline_args, namespace, arg_mode=None,
               debug=False):
    """
    Call ``function`` on command-line arguments.  Arguments can be positional
    or keyword arguments like "--foo=bar".  Arguments are by default
    heuristically evaluated.

    :type function:
      ``UserExpr``
    :param function:
      Function to apply.
    :type commandline_args:
      ``list`` of ``str``
    :param commandline_args:
      Arguments to ``function`` as strings.
    :param arg_mode:
      How to interpret ``commandline_args``.  If ``"string"``, then treat them
      as literal strings.  If ``"eval"``, then evaluate all arguments as
      expressions.  If ``"auto"`` (the default), then heuristically decide
      whether to treat as expressions or strings.
    """
    if not isinstance(function, UserExpr):
        raise TypeError
    if not callable(function.value):
        raise NotAFunctionError("Not a function", function.value)
    arg_mode = _interpret_arg_mode(arg_mode, default="auto")
    # Parse command-line arguments.
    argspec = _get_argspec(function.value)
    try:
        args, kwargs = _parse_auto_apply_args(argspec, commandline_args,
                                              namespace, arg_mode=arg_mode)
    except _ParseInterruptedWantHelp:
        usage = _get_help(function, verbosity=1)
        print(usage)
        raise SystemExit(0)
    except _ParseInterruptedWantSource:
        usage = _get_help(function, verbosity=2)
        print(usage)
        raise SystemExit(0)
    except ParseError as e:
        # Failed parsing command-line arguments.  Print usage.
        logger.error(e)
        usage = _get_help(function, verbosity=(1 if logger.info_enabled else 0))
        sys.stderr.write("\n" + usage)
        raise SystemExit(1)
    # Log what we're doing.

    logger.info("%s", _format_call(str(function.source), argspec, args, kwargs))

    # *** Call the function. ***
    f = function.value
    try:
        if debug:
            result = debug_statement("f(*args, **kwargs)")
        else:
            result = f(*args, **kwargs)
        return result
    except SystemExit:
        raise
    # TODO: handle "quit" by user here specially instead of returning None.
    # May need to reimplement pdb.runeval() so we can catch BdbQuit.
    except:
        # Handle exception in user code.
        _handle_user_exception()


@total_ordering
class LoggedList:
    """
    List that logs which members have not yet been accessed (nor removed).
    """

    _ACCESSED = object()

    def __init__(self, items):
        self._items = list(items)
        self._unaccessed = list(self._items)

    def append(self, x):
        self._unaccessed.append(self._ACCESSED)
        self._items.append(x)

    def count(self):
        return self._items.count()

    def extend(self, new_items):
        new_items = list(new_items)
        self._unaccessed.extend([self._ACCESSED] * len(new_items))
        self._items.extend(new_items)

    def index(self, x, *start_stop):
        index = self._items.index(x, *start_stop) # may raise ValueError
        self._unaccessed[index] = self._ACCESSED
        return index

    def insert(self, index, x):
        self._unaccessed.insert(index, self._ACCESSED)
        self._items.insert(index, x)

    def pop(self, index):
        self._unaccessed.pop(index)
        return self._items.pop(index)

    def remove(self, x):
        index = self._items.index(x)
        self.pop(index)

    def reverse(self):
        self._items.reverse()
        self._unaccessed.reverse()

    def sort(self):
        indexes = range(len(self._items))
        indexes.sort(key=self._items.__getitem__) # argsort
        self._items = [self._items[i] for i in indexes]
        self._unaccessed = [self._unaccessed[i] for i in indexes]

    def __add__(self, other):
        return self._items + other

    def __contains__(self, x):
        try:
            self.index(x)
            return True
        except ValueError:
            return False

    def __delitem__(self, x):
        del self._items[x]
        del self._unaccessed[x]

    def __eq__(self, other):
        if not isinstance(other, LoggedList):
            return NotImplemented
        return self._items == other._items

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, LoggedList):
            return NotImplemented
        return self._items < other._items

    def __cmp__(self, x):
        return cmp(self._items, x)

    def __getitem__(self, idx):
        result = self._items[idx]
        if isinstance(idx, slice):
            self._unaccessed[idx] = [self._ACCESSED]*len(result)
        else:
            self._unaccessed[idx] = self._ACCESSED
        return result

    def __hash__(self):
        raise TypeError("unhashable type: 'LoggedList'")

    def __iadd__(self, x):
        self.extend(x)

    def __imul__(self, n):
        self._items *= n
        self._unaccessed *= n

    def __iter__(self):
        # Todo: detect mutation while iterating.
        for i, x in enumerate(self._items):
            self._unaccessed[i] = self._ACCESSED
            yield x

    def __len__(self):
        return len(self._items)


    def __mul__(self, n):
        return self._items * n

    def __reduce__(self):
        return

    def __repr__(self):
        self._unaccessed[:] = [self._ACCESSED]*len(self._unaccessed)
        return repr(self._items)

    def __reversed__(self):
        # Todo: detect mutation while iterating.
        for i in reversed(range(len(self._items))):
            self._unaccessed[i] = self._ACCESSED
            yield self._items[i]

    def __rmul__(self, n):
        return self._items * n

    def __setitem__(self, idx, value):
        self._items[idx] = value
        if isinstance(idx, slice):
            self._unaccessed[idx] = [self._ACCESSED]*len(value)
        else:
            self._unaccessed[idx] = value

    def __str__(self):
        self._unaccessed[:] = [self._ACCESSED]*len(self._unaccessed)
        return str(self._items)

    @property
    def unaccessed(self):
        return [x for x in self._unaccessed if x is not self._ACCESSED]


@contextmanager
def SysArgvCtx(*args):
    """
    Context manager that:
      * Temporarily sets sys.argv = args.
      * At end of context, complains if any args were never accessed.
    """
    # There should always be at least one arg, since the first one is
    # the program name.
    if not args:
        raise ValueError("Missing args")
    nargs = len(args) - 1
    # Create a list proxy that will log accesses.
    argv = LoggedList(args)
    # Don't consider first argument to be interesting.
    argv[0]
    orig_argv = list(sys.argv)
    try:
        sys.argv = argv
        # Run context code.
        yield
        # Complain if there are unaccessed arguments.
        unaccessed = argv.unaccessed
        if not unaccessed:
            pass
        else:
            if nargs == 1:
                msg = ("You specified a command-line argument, but your code didn't use it: %s"
                       % (unaccessed[0],))
            elif len(unaccessed) == nargs:
                msg = ("You specified %d command-line arguments, but your code didn't use them: %s"
                       % (len(unaccessed), " ".join(unaccessed)))
            else:
                msg = ("You specified %d command-line arguments, but your code didn't use %d of them: %s"
                       % (nargs, len(unaccessed), " ".join(unaccessed)))
            msg2 = "\nIf this is intentional, access 'sys.argv[:]' somewhere in your code."
            logger.error(msg + msg2)
            raise SystemExit(1)
    finally:
        sys.argv = orig_argv


def _as_filename_if_seems_like_filename(arg):
    """
    If ``arg`` seems like a filename, then return it as one.

      >>> bool(_as_filename_if_seems_like_filename("foo.py"))
      True

      >>> bool(_as_filename_if_seems_like_filename("%foo.py"))
      False

      >>> bool(_as_filename_if_seems_like_filename("foo(bar)"))
      False

      >>> bool(_as_filename_if_seems_like_filename("/foo/bar/baz.quux-660470"))
      True

      >>> bool(_as_filename_if_seems_like_filename("../foo/bar-24084866"))
      True

    :type arg:
      ``str``
    :rtype:
      ``Filename``
    """
    try:
        filename = Filename(arg)
    except UnsafeFilenameError:
        # If the filename isn't a "safe" filename, then don't treat it as one,
        # and don't even check whether it exists.  This means that for an
        # argument like "foo(bar)" or "lambda x:x*y" we won't even check
        # existence.  This is both a performance optimization and a safety
        # valve to avoid unsafe filenames being created to intercept expressions.
        return None
    # If the argument "looks" like a filename and is unlikely to be a python
    # expression, then assume it is a filename.  We assume so regardless of
    # whether the file actually exists; if it turns out to not exist, we'll
    # complain later.
    if arg.startswith("/") or arg.startswith("./") or arg.startswith("../"):
        return filename
    if filename.ext == ".py":
        # TODO: .pyc, .pyo
        return which(arg) or filename
    # Even if it doesn't obviously look like a filename, but it does exist as
    # a filename, then use it as one.
    if filename.exists:
        return filename
    # If it's a plain name and we can find an executable on $PATH, then use
    # that.
    if re.match("^[a-zA-Z0-9_-]+$", arg):
        filename = which(arg)
        if not filename:
            return None
        if not _has_python_shebang(filename):
            logger.debug("Found %s but it doesn't seem like a python script",
                         filename)
            return None
        return filename
    return None


def _has_python_shebang(filename):
    """
    Return whether the first line contains #!...python...

    Used for confirming that an executable script found via which() is
    actually supposed to be a python script.

    Note that this test is only needed for scripts found via which(), since
    otherwise the shebang is not necessary.
    """
    assert isinstance(filename, Filename)
    with open(str(filename), 'rb') as f:
        line = f.readline(1024)
        return line.startswith(b"#!") and b"python" in line



def _interpret_arg_mode(arg, default="auto"):
    """
      >>> _interpret_arg_mode("Str")
      'string'
    """
    if arg is None:
        arg = default
    if arg == "auto" or arg == "eval" or arg == "string":
        return arg # optimization for interned strings
    rarg = str(arg).strip().lower()
    if rarg in ["eval", "evaluate", "exprs", "expr", "expressions", "expression", "e"]:
        return "eval"
    elif rarg in ["strings", "string", "str", "strs", "literal", "literals", "s"]:
        return "string"
    elif rarg in ["auto", "automatic", "a"]:
        return "auto"
    elif rarg == "error":
        # Intentionally not documented to user
        return "error"
    else:
        raise ValueError(
            "Invalid arg_mode=%r; expected one of eval/string/auto"
            % (arg,))


def _interpret_output_mode(arg, default="interactive"):
    """
      >>> _interpret_output_mode('Repr_If_Not_None')
      'repr-if-not-none'
    """
    if arg is None:
        arg = default
    rarg = str(arg).strip().lower().replace("-", "").replace("_", "")
    if rarg in ["none", "no", "n", "silent"]:
        return "silent"
    elif rarg in ["interactive", "i"]:
        return "interactive"
    elif rarg in ["print", "p", "string", "str"]:
        return "str"
    elif rarg in ["repr", "r"]:
        return "repr"
    elif rarg in ["pprint", "pp"]:
        return "pprint"
    elif rarg in ["reprifnotnone", "reprunlessnone", "rn"]:
        return "repr-if-not-none"
    elif rarg in ["pprintifnotnone", "pprintunlessnone", "ppn"]:
        return "pprint-if-not-none"
    elif rarg in ["systemexit", "exit", "raise"]:
        return "exit"
    else:
        raise ValueError(
            "Invalid output=%r; expected one of "
            "silent/interactive/str/repr/pprint/repr-if-not-none/pprint-if-not-none/exit"
            % (arg,))


def print_result(result, output_mode):
    output_mode = _interpret_output_mode(output_mode)
    if output_mode == "silent":
        return
    if output_mode == "interactive":
        # TODO: support IPython output stuff (text/plain)
        try:
            idisp = result.__interactive_display__
        except Exception:
            output_mode = "pprint-if-not-none"
        else:
            result = idisp()
            output_mode = "print-if-not-none"
        # Fall through.
    if output_mode == "str":
        print(str(result))
    elif output_mode == "repr":
        print(repr(result))
    elif output_mode == "pprint":
        import pprint
        pprint.pprint(result) # or equivalently, print pprint.pformat(result)
    elif output_mode == "repr-if-not-none":
        if result is not None:
            print(repr(result))
    elif output_mode == "print-if-not-none":
        if result is not None:
            print(result)
    elif output_mode == "pprint-if-not-none":
        if result is not None:
            import pprint
            pprint.pprint(result)
    elif output_mode == "exit":
        # TODO: only raise at end after pre_exit
        raise SystemExit(result)
    else:
        raise AssertionError("unexpected output_mode=%r" % (output_mode,))


def _get_path_links(p: Path):
    """Gets path links including all symlinks.

    Adapted from `IPython.core.interactiveshell.InteractiveShell.get_path_links`.
    """
    paths = [p]
    while p.is_symlink():
        new_path = Path(os.readlink(p))
        if not new_path.is_absolute():
            new_path = p.parent / new_path
        p = new_path
        paths.append(p)
    return paths


def _init_virtualenv():
    """Add the current virtualenv to sys.path so the user can import modules from it.

    A warning will appear suggesting the user installs IPython in the
    virtualenv, but for many cases, it probably works well enough.

    Adapted `IPython.core.interactiveshell.InteractiveShell.init_virtualenv`.
    """
    if 'VIRTUAL_ENV' not in os.environ:
        # Not in a virtualenv
        return
    elif os.environ["VIRTUAL_ENV"] == "":
        warnings.warn("Virtual env path set to '', please check if this is intended.")
        return

    p = Path(sys.executable)
    p_venv = Path(os.environ["VIRTUAL_ENV"]).resolve()

    # fallback venv detection:
    # stdlib venv may symlink sys.executable, so we can't use realpath.
    # but others can symlink *to* the venv Python, so we can't just use sys.executable.
    # So we just check every item in the symlink tree (generally <= 3)
    paths = _get_path_links(p)

    # In Cygwin paths like "c:\..." and '\cygdrive\c\...' are possible
    if len(p_venv.parts) > 2 and p_venv.parts[1] == "cygdrive":
        drive_name = p_venv.parts[2]
        p_venv = (drive_name + ":/") / Path(*p_venv.parts[3:])

    if any(p_venv == p.parents[1].resolve() for p in paths):
        # Our exe is inside or has access to the virtualenv, don't need to do anything.
        return

    if sys.platform == "win32":
        virtual_env = str(Path(os.environ["VIRTUAL_ENV"], "Lib", "site-packages"))
    else:
        virtual_env_path = Path(
            os.environ["VIRTUAL_ENV"], "lib", "python{}.{}", "site-packages"
        )
        p_ver = sys.version_info[:2]

        # Predict version from py[thon]-x.x in the $VIRTUAL_ENV
        re_m = re.search(r"\bpy(?:thon)?([23])\.(\d+)\b", os.environ["VIRTUAL_ENV"])
        if re_m:
            predicted_path = Path(str(virtual_env_path).format(*re_m.groups()))
            if predicted_path.exists():
                p_ver = re_m.groups()

        virtual_env = str(virtual_env_path).format(*p_ver)

    warnings.warn(
        "Attempting to work in a virtualenv. If you encounter problems, "
        "please install pyflyby inside the virtualenv."
    )
    import site
    sys.path.insert(0, virtual_env)
    site.addsitedir(virtual_env)


class _Namespace(object):
    fake_main: ModuleType

    def __init__(self):
        self.fake_main = ModuleType("__main__")
        _init_virtualenv()
        self.fake_main.__dict__.setdefault("__builtin__", builtins)
        self.fake_main.__dict__.setdefault("__builtins__", builtins)
        self.globals = self.fake_main.__dict__
        self.autoimported = {}

    def auto_import(self, arg):
        return auto_import(arg, [self.globals], autoimported=self.autoimported)

    def auto_eval(self, block, mode=None, info=False, auto_import=True,
                  debug=False):
        """
        Evaluate ``block`` with auto-importing.
        """
        # Equivalent to::
        #   auto_eval(arg, mode=mode, flags=FLAGS, globals=self.globals)
        # but better logging and error raising.
        if not isinstance(block, PythonBlock):
            block = PythonBlock(block, flags=FLAGS, auto_flags=True)
        if auto_import and not self.auto_import(block):
            missing = find_missing_imports(block, [self.globals])
            mstr = ", ".join(repr(str(x)) for x in missing)
            if len(missing) == 1:
                msg = "name %s is not defined and not importable" % mstr
            elif len(missing) > 1:
                msg = "names %s are not defined and not importable" % mstr
            else:
                raise AssertionError
            raise UnimportableNameError(msg)
        if info:
            logger.info(block)
        try:
            # TODO: enter text into linecache
            if debug:
                return debug_statement(block, self.globals)
            else:
                code = block.compile(mode=mode)
                try:
                    main = sys.modules["__main__"]
                    sys.modules["__main__"] = self.fake_main

                    return eval(code, self.globals, self.globals)
                finally:
                    sys.modules["__main__"] = main
        except SystemExit:
            raise
        except:
            _handle_user_exception()

    def __repr__(self):
        return "<{} object at 0x{:0x} \nglobals:{} \nautoimported:{}>".format(
            type(self).__name__, id(self), self.globals, self.autoimported
        )


class _PyMain(object):

    def __init__(self, args):
        self.main_args = args
        self.namespace = _Namespace()
        self.result = None
        self.ipython_app = None

    def exec_stdin(self, cmd_args):
        arg_mode = _interpret_arg_mode(self.arg_mode, default="string")
        output_mode = _interpret_output_mode(self.output_mode, default="silent")
        cmd_args = [UserExpr(a, self.namespace, arg_mode).value
                    for a in cmd_args]
        with SysArgvCtx(*cmd_args):
            result = self.namespace.auto_eval(Filename.STDIN, debug=self.debug)
            print_result(result, output_mode)
            self.result = result

    def eval(self, cmd, cmd_args):
        arg_mode = _interpret_arg_mode(self.arg_mode, default="string")
        output_mode = _interpret_output_mode(self.output_mode)
        cmd_args = [UserExpr(a, self.namespace, arg_mode).value
                    for a in cmd_args]
        with SysArgvCtx("-c", *cmd_args):
            cmd = PythonBlock(cmd)
            result = self.namespace.auto_eval(cmd, info=True, debug=self.debug)
            # TODO: make auto_eval() plow ahead even if there are unimportable
            # names, after warning
            print_result(result, output_mode)
            self.result = result

    def execfile(self, filename_arg, cmd_args):
        # TODO: pass filename to import db target_filename; unit test.
        # TODO: set __file__
        # TODO: support compiled (.pyc/.pyo) files
        arg_mode = _interpret_arg_mode(self.arg_mode, default="string")
        output_mode = _interpret_output_mode(self.output_mode)
        cmd_args = [UserExpr(a, self.namespace, arg_mode).value
                    for a in cmd_args]
        additional_msg = ""
        if isinstance(filename_arg, Filename):
            filename = filename_arg
        elif filename_arg == "-":
            filename = Filename.STDIN
        elif "/" in filename_arg:
            filename = Filename(filename_arg)
        else:
            filename = which(filename_arg)
            if not filename:
                filename = Filename(filename_arg)
                additional_msg = (" (and didn't find %s on $PATH)"
                                  % (filename_arg,))
            elif not _has_python_shebang(filename):
                additional_msg = (" (found %s but it doesn't look "
                                  "like python source"
                                  % (filename,))
                filename = Filename(filename_arg)
        if not filename.exists:
            raise Exception("No such file: %s%s" % (filename, additional_msg))
        with SysArgvCtx(str(filename), *cmd_args):
            sys.path.insert(0, str(filename.dir))
            self.namespace.globals["__file__"] = str(filename)
            result = self.namespace.auto_eval(filename, debug=self.debug)
            print_result(result, output_mode)
            self.result = result

    def apply(self, function, cmd_args):
        arg_mode = _interpret_arg_mode(self.arg_mode, default="auto")
        output_mode = _interpret_output_mode(self.output_mode)
        # Todo: what should we set argv to?
        result = auto_apply(function, cmd_args, self.namespace, arg_mode,
                            debug=self.debug)
        print_result(result, output_mode)
        self.result = result

    def _seems_like_runnable_module(self, arg):
        if not is_identifier(arg, dotted=True):
            # It's not a single (dotted) identifier.
            return False
        if not find_missing_imports(arg, [{}]):
            # It's off of a builtin, e.g. "str.upper"
            return False
        m = ModuleHandle(arg)
        if m.parent:
            # Auto-import the parent, which is necessary in order to get the
            # filename of the module.  ``ModuleHandle.filename`` does this
            # automatically, but we do it explicitly here so that we log
            # the import of the parent module.
            if not self.namespace.auto_import(str(m.parent.name)):
                return False
        if not m.filename:
            logger.debug("Module %s doesn't have a source filename", m)
            return False
        # TODO: check that the source accesses __main__ (ast traversal?)
        return True

    def heuristic_cmd(self, cmd, cmd_args, function_name=None):
        output_mode = _interpret_output_mode(self.output_mode)
        # If the "command" is just a module name, then call run_module.  Make
        # sure we check that it's not a builtin.
        if self._seems_like_runnable_module(str(cmd)):
            self.heuristic_run_module(str(cmd), cmd_args)
            return
        # FIXME TODO heed arg_mode for non-apply case.  This is tricky to
        # implement; will require assigning some proxy class to sys.argv
        # that's more sophisticated than just logging.
        with SysArgvCtx("-c", *cmd_args):
            # Log the expression before we evaluate it, unless we're likely to
            # log another substantially similar line.  (We can only guess
            # heuristically whether it's interesting enough to log it.  And we
            # can't know whether the result will be callable until we evaluate
            # it.)
            info = not re.match("^[a-zA-Z0-9_.]+$", function_name)
            result = self.namespace.auto_eval(cmd, info=info, debug=self.debug)
            if callable(result):
                function = UserExpr(
                    result, self.namespace, "raw_value", function_name)
                result = auto_apply(function, cmd_args, self.namespace,
                                    self.arg_mode, debug=self.debug)
                print_result(result, output_mode)
                self.result = result
                sys.argv[:] # mark as accessed
            else:
                if not info:
                    # We guessed wrong earlier and didn't log yet; log now.
                    logger.info(cmd)
                print_result(result, output_mode)
                self.result = result
                unaccessed = sys.argv.unaccessed
                if unaccessed:
                    logger.error(
                        "%s is not callable.  Unexpected argument(s): %s",
                        result, " ".join(unaccessed))
                sys.argv[:] # don't complain again

    def run_module(self, module, args):
        arg_mode = _interpret_arg_mode(self.arg_mode, default="string")
        if arg_mode != "string":
            raise NotImplementedError(
                "run_module only supports string arguments")
        module = ModuleHandle(module)
        logger.info("python -m %s", ' '.join([str(module.name)] + args))
        # Imitate 'python -m'.
        # TODO: include only the traceback below runpy.run_module
        #   os.execvp(sys.executable, [sys.argv[0], "-m", modname] + args)
        sys.argv = [str(module.filename)] + args
        import runpy
        if self.debug:
            # TODO: break closer to user code
            debugger()
        try:
            runpy.run_module(str(module.name), run_name="__main__")
        except SystemExit:
            raise
        except:
            _handle_user_exception()

    def heuristic_run_module(self, module, args):
        module = ModuleHandle(module)
        # If the user ran 'py numpy --version', then print the numpy
        # version, i.e. same as 'py --version numpy'.  This has the
        # downside of shadowing a possible "--version" feature
        # implemented by the module itself.  However, this is probably
        # not a big deal, because (1) a full-featured program that
        # supports --version would normally have a driver script and
        # not rely on 'python -m foo'; (2) it would probably do
        # something similar anyway; (3) the user can do 'py -m foo
        # --version' if necessary.
        if len(args)==1 and args[0] in ["--version", "-version"]:
            self.print_version(module)
            return
        if len(args)==1 and args[0] in ["--help", "-help", "--h", "-h",
                                        "--?", "-?", "?"]:
            expr = UserExpr(module.module, None, "raw_value",
                            source=str(module.name))
            usage = _get_help(expr, 1)
            print(usage)
            return
        if len(args)==1 and args[0] in ["--source", "-source",
                                        "--??", "-??", "??"]:
            expr = UserExpr(module.module, None, "raw_value",
                            source=str(module.name))
            usage = _get_help(expr, 2)
            print(usage)
            return
        # TODO: check if module checks __main__
        self.run_module(module, args)

    def print_version(self, arg):
        if not arg:
            print_version_and_exit()
            return
        if isinstance(arg, (ModuleHandle, types.ModuleType)):
            module = ModuleHandle(arg).module
        else:
            module = self.namespace.auto_eval(arg, mode="eval")
        if not isinstance(module, types.ModuleType):
            raise TypeError("print_version(): got a %s instead of a module"
                            % (type(module).__name__,))
        try:
            version = module.__version__
        except AttributeError:
            raise AttributeError(
                "Module %s does not have a __version__ attribute"
                % (module.__name__,))
        print(version)

    def print_help(self, objname, verbosity=1):
        objname = objname and objname.strip()
        if not objname:
            print(__doc__)
            return
        expr = UserExpr(objname, self.namespace, "eval")
        usage = _get_help(expr, verbosity)
        print(usage)

    def create_ipython_app(self):
        """
        Create an IPython application and initialize it, but don't start it.
        """
        assert self.ipython_app is None
        self.ipython_app = get_ipython_terminal_app_with_autoimporter()

    def start_ipython(self, args=[]):
        user_ns = self.namespace.globals
        start_ipython_with_autoimporter(args, _user_ns=user_ns,
                                        app=self.ipython_app)
        # Don't need to do another interactive session after this one
        # (i.e. make 'py --interactive' the same as 'py').
        self.interactive = False

    def _parse_global_opts(self):
        args = list(self.main_args)
        self.add_deprecated_builtins = False
        self.debug       = False
        self.interactive = False
        self.verbosity   = 1
        self.arg_mode    = None
        self.output_mode = None
        postmortem = 'auto'
        while args:
            arg = args[0]
            if arg in ["debug", "pdb", "ipdb", "dbg"]:
                argname = "debug"
            elif not arg.startswith("-"):
                break
            elif arg.startswith("--"):
                argname = arg[2:]
            else:
                argname = arg[1:]
            argname, equalsign, value = argname.partition("=")
            def popvalue():
                if equalsign:
                    return value
                else:
                    try:
                        return args.pop(0)
                    except IndexError:
                        raise ValueError("expected argument to %s" % arg)
            def novalue():
                if equalsign:
                    raise ValueError("unexpected argument %s" % arg)
            if argname in ["interactive", "i"]:
                novalue()
                self.interactive = True
                del args[0]
                # Create and initialize the IPython app now (but don't start
                # it yet).  We'll use it later.  The reason to initialize it
                # now is that the code that we're running might check if it's
                # running in interactive mode based on whether an IPython app
                # has been initialized.  Some user code even initializes
                # things differently at module import time based on this.
                self.create_ipython_app()
            elif argname in ["debug", "pdb", "ipdb", "dbg", "d"]:
                novalue()
                self.debug = True
                del args[0]
            if argname == "verbose":
                novalue()
                logger.set_level("DEBUG")
                del args[0]
                continue
            if argname in ["quiet", "q"]:
                novalue()
                logger.set_level("ERROR")
                del args[0]
                continue
            if argname in ["safe"]:
                del args[0]
                novalue()
                self.arg_mode = _interpret_arg_mode("string")
                # TODO: make this less hacky, something like
                #   self.import_db = ""
                # TODO: also turn off which() behavior
                os.environ["PYFLYBY_PATH"] = "EMPTY"
                continue
            if argname in ["arguments", "argument", "args", "arg",
                           "arg_mode", "arg-mode", "argmode"]:
                # Interpret --args=eval|string|auto.
                # Note that if the user didn't specify --args, then we
                # intentionally leave ``opts.arg_mode`` set to ``None`` for now,
                # because the default varies per action.
                del args[0]
                self.arg_mode = _interpret_arg_mode(popvalue())
                continue
            if argname in ["output", "output_mode", "output-mode",
                           "out", "outmode", "out_mode", "out-mode", "o"]:
                del args[0]
                self.output_mode = _interpret_output_mode(popvalue())
                continue
            if argname in ["print", "pprint", "silent", "repr"]:
                del args[0]
                novalue()
                self.output_mode = _interpret_output_mode(argname)
                continue
            if argname in ["postmortem"]:
                del args[0]
                v = (value or "").lower().strip()
                if v in ["yes", "y", "always", "true", "t", "1", "enable", ""]:
                    postmortem = True
                elif v in ["no", "n", "never", "false", "f", "0", "disable"]:
                    postmortem = False
                elif v in ["auto", "automatic", "default", "if-tty"]:
                    postmortem = "auto"
                else:
                    raise ValueError(
                        "unexpected %s=%s.  "
                        "Try --postmortem=yes or --postmortem=no."
                        % (argname, value))
                continue
            if argname in ["no-postmortem", "np"]:
                del args[0]
                novalue()
                postmortem = False
                continue
            if argname in ["add-deprecated-builtins", "add_deprecated_builtins"]:
                del args[0]
                self.add_deprecated_builtins = True
                continue
            break
        self.args = args
        if postmortem == "auto":
            postmortem = os.isatty(1)
        global _enable_postmortem_debugger
        _enable_postmortem_debugger = postmortem

    def _enable_debug_tools(self, *, add_deprecated: bool):
        # Enable a bunch of debugging tools.
        enable_faulthandler()
        enable_signal_handler_debugger()
        enable_sigterm_handler()
        add_debug_functions_to_builtins(add_deprecated=add_deprecated)

    def run(self):
        # Parse global options.
        sys.orig_argv = list(sys.argv)
        self._parse_global_opts()
        self._enable_debug_tools(add_deprecated=self.add_deprecated_builtins)
        self._run_action()
        self._pre_exit()

    def _run_action(self):
        args = self.args
        if not args or args[0] == "-":
            if os.isatty(0):
                # The user specified no arguments (or only a "-") and stdin is a
                # tty.  Run ipython with autoimporter enabled, i.e. equivalent to
                # autoipython.  Note that we directly start IPython in the same
                # process, instead of using subprocess.call(['autoipython']),
                # because the latter messes with Control-C handling.
                # TODO: add 'py shell' and make this an alias.
                # TODO: if IPython isn't installed, then do our own
                # interactive REPL with code.InteractiveConsole, readline, and
                # autoimporter.
                self.start_ipython()
                return
            else:
                # Emulate python args.
                cmd_args = args or [""]
                # Execute code from stdin, with auto importing.
                self.exec_stdin(cmd_args)
                return

        # Consider --action=arg, --action arg, -action=arg, -action arg,
        # %action arg.
        arg0 = args.pop(0)
        if not arg0.strip():
            raise ValueError("got empty string as first argument")
        if arg0.startswith("--"):
            action, equalsign, cmdarg = arg0[2:].partition("=")
        elif arg0.startswith("-"):
            action, equalsign, cmdarg = arg0[1:].partition("=")
        elif arg0.startswith("%"):
            action, equalsign, cmdarg = arg0[1:], None, None
        elif len(arg0) > 1 or arg0 == "?":
            action, equalsign, cmdarg = arg0, None, None
        else:
            action, equalsign, cmdarg = None, None, None
        def popcmdarg():
            if equalsign:
                return cmdarg
            else:
                try:
                    return args.pop(0)
                except IndexError:
                    raise ValueError("expected argument to %s" % arg0)
        def nocmdarg():
            if equalsign:
                raise ValueError("unexpected argument %s" % arg0)

        if action in ["eval", "c", "e"]:
            # Evaluate a command from the command-line, with auto importing.
            # Supports expressions as well as statements.
            # Note: Regular python supports "python -cfoo" as equivalent to
            # "python -c foo".  For now, we intentionally don't support that.
            cmd = popcmdarg()
            self.eval(cmd, args)
        elif action in ["file", "execfile", "execf", "runfile", "run", "f",
                        "python"]:
            # Execute a file named on the command-line, with auto importing.
            cmd = popcmdarg()
            self.execfile(cmd, args)
        elif action in ["apply", "call"]:
            # Call a function named on the command-line, with auto importing and
            # auto evaluation of arguments.
            function_name = popcmdarg()
            function = UserExpr(function_name, self.namespace, "eval")
            self.apply(function, args)
        elif action in ["map"]:
            # Call function on each argument.
            # TODO: instead of making this a standalone mode, change this to a
            # flag that can eval/apply/exec/etc.  Set "_" to each argument.
            # E.g. py --map 'print _' obj1 obj2
            #      py --map _.foo obj1 obj2
            #      py --map '_**2' 3 4 5
            # when using heuristic mode, "lock in" the action mode on the
            # first argument.
            function_name = popcmdarg()
            function = UserExpr(function_name, self.namespace, "eval")
            if args and args[0] == '--':
                for arg in args[1:]:
                    self.apply(function, ['--', arg])
            else:
                for arg in args:
                    self.apply(function, [arg])
        elif action in ["xargs"]:
            # TODO: read lines from stdin and map.  default arg_mode=string
            raise NotImplementedError("TODO: xargs")
        elif action in ["module", "m", "runmodule", "run_module", "run-module"]:
            # Exactly like `python -m'.  Intentionally does NOT do auto
            # importing within the module, because modules should not be
            # sloppy; they should instead be tidied to have the correct
            # imports.
            modname = popcmdarg()
            self.run_module(modname, args)
        elif arg0.startswith("-m"):
            # Support "py -mbase64" in addition to "py -m base64".
            modname = arg0[2:]
            self.run_module(modname, args)
        elif action in ["attach"]:
            pid = int(popcmdarg())
            nocmdarg()
            attach_debugger(pid)
        elif action in ["stack", "stack_trace", "stacktrace", "backtrace", "bt"]:
            pid = int(popcmdarg())
            nocmdarg()
            print("Stack trace for process %s:" % (pid,))
            remote_print_stack(pid)
        elif action in ["ipython", "ip"]:
            # Start IPython.
            self.start_ipython(args)
        elif action in ["notebook", "nb"]:
            # Start IPython notebook.
            nocmdarg()
            self.start_ipython(["notebook"] + args)
        elif action in ["kernel"]:
            # Start IPython kernel.
            nocmdarg()
            self.start_ipython(["kernel"] + args)
        elif action in ["qtconsole", "qt"]:
            # Start IPython qtconsole.
            nocmdarg()
            self.start_ipython(["qtconsole"] + args)
        elif action in ["console"]:
            # Start IPython console (with new kernel).
            nocmdarg()
            self.start_ipython(["console"] + args)
        elif action in ["existing"]:
            # Start IPython console (with existing kernel).
            if equalsign:
                args.insert(0, cmdarg)
            self.start_ipython(["console", "--existing"] + args)
        elif action in ["nbconvert"]:
            # Start IPython nbconvert.  (autoimporter is irrelevant.)
            if equalsign:
                args.insert(0, cmdarg)
            start_ipython_with_autoimporter(["nbconvert"] + args)
        elif action in ["timeit"]:
            # TODO: make --timeit and --time flags which work with any mode
            # and heuristic, instead of only eval.
            # TODO: fallback if IPython isn't available.  above todo probably
            # requires not using IPython anyway.
            nocmdarg()
            run_ipython_line_magic("%timeit " + ' '.join(args))
        elif action in ["time"]:
            # TODO: make --timeit and --time flags which work with any mode
            # and heuristic, instead of only eval.
            # TODO: fallback if IPython isn't available.  above todo probably
            # requires not using IPython anyway.
            nocmdarg()
            run_ipython_line_magic("%time " + ' '.join(args))
        elif action in ["version"]:
            if equalsign:
                args.insert(0, cmdarg)
            self.print_version(args[0] if args else None)
        elif action in ["help", "h", "?"]:
            if equalsign:
                args.insert(0, cmdarg)
            self.print_help(args[0] if args else None, verbosity=1)
        elif action in ["pinfo"]:
            self.print_help(popcmdarg(), verbosity=1)
        elif action in ["source", "pinfo2", "??"]:
            self.print_help(popcmdarg(), verbosity=2)

        elif arg0.startswith("-"):
            # Unknown argument.
            msg = "Unknown option %s" % (arg0,)
            if arg0.startswith("-c"):
                msg += "; do you mean -c %s?" % (arg0[2:])
            syntax(msg, usage=usage)

        elif arg0.startswith("??"):
            # TODO: check number of args
            self.print_help(arg0[2:], verbosity=2)

        elif arg0.endswith("??"):
            # TODO: check number of args
            self.print_help(arg0[:-2], verbosity=2)

        elif arg0.startswith("?"):
            # TODO: check number of args
            self.print_help(arg0[1:], verbosity=1)

        elif arg0.endswith("?"):
            # TODO: check number of args
            self.print_help(arg0[:-1], verbosity=1)

        elif arg0.startswith("%"):
            run_ipython_line_magic(' '.join([arg0]+args))

        # Heuristically choose the behavior automatically based on what the
        # argument looks like.
        else:
            filename = _as_filename_if_seems_like_filename(arg0)
            if filename:
                # Implied --execfile.
                self.execfile(filename, args)
                return
            if not args and arg0.isdigit():
                if self.debug:
                    attach_debugger(int(arg0, 10))
                    return
                else:
                    logger.error(
                        "Use py -d %s if you want to attach a debugger", arg0)
                    raise SystemExit(1)
            # Implied --eval.
            # When given multiple arguments, first see if the args can be
            # concatenated and parsed as a single python program/expression.
            # But don't try this if any arguments look like options, empty
            # string or whitespace, etc.
            # TODO: refactor
            if (args and
                self.arg_mode == None and
                not any(re.match(r"\s*$|-[a-zA-Z-]", a) for a in args)):
                cmd = PythonBlock(" ".join([arg0]+args),
                                  flags=FLAGS, auto_flags=True)
                if cmd.parsable and self.namespace.auto_import(cmd):
                    with SysArgvCtx("-c"):
                        output_mode = _interpret_output_mode(self.output_mode)
                        result = self.namespace.auto_eval(
                            cmd, info=True, auto_import=False)
                        print_result(result, output_mode)
                        self.result = result
                        return
                # else fall through
            # Heuristic based on first arg: try run_module, apply, or exec/eval.
            cmd = PythonBlock(arg0, flags=FLAGS, auto_flags=True)
            if not cmd.parsable:
                logger.error(
                    "Could not interpret as filename or expression: %s",
                    arg0)
                syntax(usage=usage)
            self.heuristic_cmd(cmd, args, function_name=arg0)

    def _pre_exit(self):
        self._pre_exit_matplotlib_show()
        self._pre_exit_interactive_shell()

    def _pre_exit_matplotlib_show(self):
        """
        If matplotlib.pyplot (pylab) is loaded, then call the show() function.
        This will cause the program to block until all figures are closed.
        Without this, a command like 'py plot(...)' would exit immediately.
        """
        if self.interactive:
            return
        try:
            pyplot = sys.modules["matplotlib.pyplot"]
        except KeyError:
            return
        pyplot.show()

    def _pre_exit_interactive_shell(self):
        if self.interactive:
            assert self.ipython_app is not None
            self.namespace.globals["_"] = self.result
            self.start_ipython()


def py_main(args=None):
    if args is None:
        args = sys.argv[1:]
    _PyMain(args).run()
