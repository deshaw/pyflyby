# pyflyby/_interactive.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __builtin__
import contextlib
import os
import subprocess
import sys

from   pyflyby._autoimp         import (auto_import, interpret_namespaces,
                                        load_symbol)
from   pyflyby._file            import Filename, atomic_write_file
from   pyflyby._idents          import is_identifier
from   pyflyby._importdb        import ImportDB
from   pyflyby._log             import logger
from   pyflyby._modules         import ModuleHandle
from   pyflyby._util            import CwdCtx, memoize


# TODO: also support arbitrary code (in the form of a lambda and/or
# assignment) as new way to do "lazy" creations, e.g. foo = a.b.c(d.e+f.g())


def initialize_ipython(argv=None):
    """
    Initialize an IPython shell, but don't start it yet.

    @rtype:
      C{callable}
    @return:
      The function that can be called to start the console terminal.
    """
    import IPython
    # The following has been tested on IPython 1.2, 2.1.
    try:
        TerminalIPythonApp = IPython.terminal.ipapp.TerminalIPythonApp
    except AttributeError:
        pass
    else:
        app = TerminalIPythonApp.instance()
        app.initialize(argv)
        return app.start
    # The following has been tested on IPython 0.13.
    try:
        TerminalIPythonApp = IPython.frontend.terminal.ipapp.TerminalIPythonApp
    except AttributeError:
        pass
    else:
        app = TerminalIPythonApp.instance()
        app.initialize(argv)
        return app.start
    raise RuntimeError(
        "Couldn't get TerminalIPythonApp class.  "
        "Is your IPython version too old (or too new)?  "
        "IPython.__version__=%r" % (IPython.__version__))


def _python_can_import_pyflyby(expected_path, sys_path_entry=None):
    """
    Try to figure out whether python (when started from scratch) can get the
    same pyflyby package as the current process.
    """
    with CwdCtx("/"):
        cmd = 'import pyflyby; print pyflyby.__path__[0]'
        if sys_path_entry is not None:
            impcmd = "import sys; sys.path.insert(0, %r)\n" % (sys_path_entry,)
            cmd = impcmd + cmd
        proc = subprocess.Popen(
            [sys.executable, '-c', cmd],
            stdin=open("/dev/null"),
            stdout=subprocess.PIPE,
            stderr=open("/dev/null",'w'))
        result = proc.communicate()[0].strip()
    if not result:
        return False
    try:
        return os.path.samefile(result, expected_path)
    except OSError:
        return False


def install_in_ipython_startup_file():
    """
    Install the call to 'pyflyby.install_auto_importer()' to the default
    IPython startup file.
    """
    import IPython
    ipython_dir = Filename(IPython.utils.path.get_ipython_dir())
    if not ipython_dir.isdir:
        raise RuntimeError(
            "Couldn't find IPython config dir.  Tried %s" % (ipython_dir,))
    startup_dir = ipython_dir / "profile_default" / "startup"
    if not startup_dir.isdir:
        raise RuntimeError(
            "Couldn't find IPython startup dir.  Tried %s" % (startup_dir,))
    fn = startup_dir / "50-pyflyby.py"
    if fn.exists:
        logger.info("Doing nothing, because %s already exists", fn)
        return
    contents = (
        "import pyflyby\n"
        "pyflyby.install_auto_importer()\n"
    )
    import pyflyby
    pyflyby_path = pyflyby.__path__[0]
    if not _python_can_import_pyflyby(pyflyby_path):
        path_entry = os.path.dirname(os.path.realpath(pyflyby_path))
        assert _python_can_import_pyflyby(pyflyby_path, path_entry)
        contents = (
            "import sys\n"
            "sys.path.insert(0, %r)\n" % (path_entry,)
        ) + contents
    logger.info("Writing to %s:\n%s", fn, contents)
    atomic_write_file(fn, contents)


@contextlib.contextmanager
def InterceptPrintsDuringPromptCtx():
    """
    Hook our local output function so that:
      1. Before the first print, if any, print an extra newline.
      2. Upon context exit, if any lines were printed, redisplay the prompt.
    """
    ip = get_ipython_safe()
    try:
        readline       = ip.readline
        prompt_manager = ip.prompt_manager
        redisplay      = readline.redisplay
        input_splitter = ip.input_splitter
    except AttributeError:
        yield
        return
    def pre():
        print()
        sys.stdout.flush()
    def post():
        # Re-display the current line.
        if input_splitter.source == "":
            # First line
            prompt = ip.separate_in + prompt_manager.render("in")
        else:
            # Non-first line
            prompt = prompt_manager.render("in2")
        prompt = prompt.replace("\x01", "").replace("\x02", "")
        line = readline.get_line_buffer()[:readline.get_endidx()]
        sys.stdout.write(prompt + line)
        redisplay()
        sys.stdout.flush()
    with logger.HookCtx(pre=pre, post=post):
        yield


@memoize
def get_ipython_safe():
    """
    Get an IPython shell instance, if we are inside an IPython session.

    If we are not inside an IPython session, don't initialize one.

    @rtype:
      C{IPython.core.interactiveshell.InteractiveShell}
    """
    try:
        IPython = sys.modules['IPython']
    except KeyError:
        # The 'IPython' module isn't already loaded, so we're not in an
        # IPython session.  Don't import it.
        logger.debug("[IPython not loaded]")
        return None
    # IPython 1.0+: use IPython.get_ipython().  This doesn't create an
    # instance if it doesn't already exist.
    try:
        get_ipython = IPython.get_ipython
    except AttributeError:
        pass # not IPython 1.0+
    else:
        return get_ipython()
    # IPython 0.11+: IPython.core.interactiveshell.InteractiveShell._instance.
    # [The public method IPython.core.ipapi.get() also returns this, but we
    # don't want to call that, because get() creates an IPython shell if it
    # doesn't already exist, which we don't want.]
    try:
        return IPython.core.interactiveshell.InteractiveShell._instance
    except AttributeError:
        pass # not IPython 0.11+
    # IPython 0.10+: IPython.ipapi.get().IP
    try:
        get = IPython.ipapi.get
    except AttributeError:
        pass # not IPython 0.10+
    else:
        ipsh = get()
        if ipsh is not None:
            return ipsh.IP
        else:
            return None
    # Couldn't get IPython.
    logger.debug("Couldn't get IPython shell instance (IPython version: %s)",
                 IPython.__version__)
    return None


def _ipython_namespaces(ip):
    """
    Return the (global) namespaces used for IPython.

    The ordering follows IPython convention of most-local to most-global.

    @type ip:
      C{IPython.core.InteractiveShell}
    @rtype:
      C{list}
    @return:
      List of (name, namespace_dict) tuples.
    """
    # This list is copied from IPython 2.2's InteractiveShell._ofind().
    # Earlier versions of IPython (back to 1.x) also include
    # ip.alias_manager.alias_table at the end.  This doesn't work in IPython
    # 2.2 and isn't necessary anyway in earlier versions of IPython.
    return [ ('Interactive'         , ip.user_ns),
             ('Interactive (global)', ip.user_global_ns),
             ('Python builtin'      , __builtin__.__dict__),
    ]


# TODO class NamespaceList(tuple):



def get_global_namespaces():
    """
    Get the global interactive namespaces.

    @rtype:
      C{list} of C{dict}
    """
    ip = get_ipython_safe()
    if ip:
        return [ns for nsname, ns in _ipython_namespaces(ip)][::-1]
    else:
        import __main__
        return [__builtin__.__dict__, __main__.__dict__]


def complete_symbol(fullname, namespaces, db=None):
    """
    Enumerate possible completions for C{fullname}.

    Includes globals and auto-importable symbols.

      >>> complete_symbol("threadi", [])                # doctest:+ELLIPSIS
      [...'threading'...]

    Completion works on attributes, even on modules not yet imported - modules
    are auto-imported first if not yet imported:

      >>> ns = {}
      >>> complete_symbol("threading.Threa", namespaces=[ns])
      [PYFLYBY] import threading
      ['threading.Thread', 'threading.ThreadError']

      >>> 'threading' in ns
      True

      >>> complete_symbol("threading.Threa", namespaces=[ns])
      ['threading.Thread', 'threading.ThreadError']

    We only need to import *parent* modules (packages) of the symbol being
    completed.  If the user asks to complete "foo.bar.quu<TAB>", we need to
    import foo.bar, but we don't need to import foo.bar.quux.

    @type fullname:
      C{str}
    @param fullname:
      String to complete.  ("Full" refers to the fact that it should contain
      dots starting from global level.)
    @type namespaces:
      C{dict} or C{list} of C{dict}
    @param namespaces:
      Namespaces of (already-imported) globals.
    @type db:
      L{importDB}
    @param db:
      Import database to use.
    @rtype:
      C{list} of C{str}
    @return:
      Completion candidates.
    """
    namespaces = interpret_namespaces(namespaces)
    logger.debug("complete_symbol(%r)", fullname)
    # Require that the input be a prefix of a valid symbol.
    if not is_identifier(fullname, dotted=True, prefix=True):
        return []
    # Get the database of known imports.
    db = ImportDB.interpret_arg(db, target_filename=".")
    known = db.known_imports
    if '.' not in fullname:
        # Check global names, including global-level known modules and
        # importable modules.
        results = set()
        for ns in namespaces:
            for name in ns:
                if '.' not in name:
                    results.add(name)
        results.update(known.member_names.get("", []))
        results.update([str(m) for m in ModuleHandle.list()])
        assert all('.' not in r for r in results)
        results = sorted([r for r in results if r.startswith(fullname)])
    else:
        # Check members, including known sub-modules and importable sub-modules.
        splt = fullname.rsplit(".", 1)
        pname, attrname = splt
        try:
            parent = load_symbol(pname, namespaces, autoimport=True, db=db)
        except AttributeError:
            # Even after attempting auto-import, the symbol is still
            # unavailable.  Nothing to complete.
            logger.debug("complete_symbol(%r): couldn't load symbol %r", fullname, pname)
            return []
        results = set()
        results.update(_list_members_for_completion(parent))
        if sys.modules.get(pname, object()) is parent and parent.__name__ == pname:
            results.update(known.member_names.get(pname, []))
            results.update([m.name.parts[-1]
                            for m in ModuleHandle(parent).submodules])
        results = sorted([r for r in results if r.startswith(attrname)])
        results = ["%s.%s" % (pname, r) for r in results]
    return results


def _list_members_for_completion(obj):
    """
    Enumerate the existing member attributes of an object.
    This emulates the regular Python/IPython completion items.

    It does not include not-yet-imported submodules.

    @param obj:
      Object whose member attributes to enumerate.
    @rtype:
      C{list} of C{str}
    """
    ip = get_ipython_safe()
    if ip is None:
        words = dir(obj)
    else:
        from IPython.utils import generics
        from IPython.utils.dir2 import dir2
        from IPython.core.error import TryNext
        if ip.Completer.limit_to__all__ and hasattr(obj, '__all__'):
            try:
                words = getattr(obj, '__all__')
            except:
                return []
        else:
            words = dir2(obj)
            try:
                words = generics.complete_object(obj, words)
            except TryNext:
                pass
    return [w for w in words if isinstance(w, basestring)]


def _complete_symbol_during_prompt(fullname):
    with InterceptPrintsDuringPromptCtx():
        return complete_symbol(fullname, get_global_namespaces())



class _AutoImporter_ast_transformer(object):
    """
    A NodeVisitor-like wrapper around C{auto_import_for_ast} for the API that
    IPython 1.x's C{ast_transformers} needs.
    """

    def visit(self, node):
        try:
            # We don't actually transform the node; we just use the
            # ast_transformers mechanism instead of the prefilter mechanism as
            # an optimization to avoid re-parsing the text into an AST.
            auto_import(node, get_global_namespaces())
            return node
        except:
            import traceback
            traceback.print_exc()
            raise


class _AutoImporter_prefilter_checker(object):
    """
    A prefilter checker for IPython < 1.0.
    """
    priority = 1
    enabled = True

    def check(self, line_info):
        logger.debug("prefilter %r", line_info.line)
        auto_import(line_info.line, get_global_namespaces())
        return None



@memoize
def install_auto_importer():
    """
    Install the auto-importer into IPython.
    """
    ip = get_ipython_safe()
    if not ip:
        return
    import IPython
    logger.debug("Initializing pyflyby auto importer for IPython version %s", IPython.__version__)

    # Install a pre-code-execution hook.
    #
    # There are a few different places within IPython we can consider hooking:
    #   * ip.input_transformer_manager.logical_line_transforms
    #   * ip.compiler.ast_parse
    #   * ip.prefilter_manager.checks
    #   * ip.ast_transformers
    #   * ip.hooks['pre_run_code_hook']
    #   * ip._ofind
    #
    # We choose to hook in two places: (1) _ofind and (2) ast_transformers.
    # The motivation follows.  We want to handle auto-imports for all of these
    # input cases:
    #   (1) "foo.bar"
    #   (2) "arbitrarily_complicated_stuff((lambda: foo.bar)())"
    #   (3) "foo.bar?", "foo.bar??" (pinfo/pinfo2)
    #   (4) "foo.bar 1, 2" => "foo.bar(1, 2)" (autocall)
    #
    # Case 1 is the easiest and can be handled by nearly any method.  Case 2
    # must be done either as a prefilter or as an AST transformer.  Cases 3
    # and 4 must be done either as an input line transformer or by
    # monkey-patching _ofind, because by the time the
    # prefilter/ast_transformer is called, it's too late.
    #
    # To handle case 2, we use an AST transformer (for IPython > 1.0), or
    # monkey-patch ip.compile.ast_parse() (for IPython < 1.0).
    # prefilter_manager.checks() is the "supported" way to add a pre-execution
    # hook, but it only works for single lines, not for multi-line cells.
    # (There is no explanation in the IPython source for why prefilter hooks
    # are seemingly intentionally skipped for multi-line cells).
    #
    # To handle cases 3/4 (pinfo/autocall), we choose to hook _ofind.  This is
    # a private function that is called by both pinfo and autocall code paths.
    # (Alternatively, we could have added something to the
    # logical_line_transforms.  The downside of that is that we would need to
    # re-implement all the parsing perfectly matching IPython.  Although
    # monkey-patching is in general bad, it seems the lesser of the two evils
    # in this case.)
    #
    # Since we have two invocations of handle_auto_imports(), case 1 is
    # handled twice.  That's fine because it runs quickly.

    # Hook _ofind.
    if hasattr(ip, "_ofind"):
        orig_ofind = ip._ofind
        def wrapped_ofind(oname, namespaces=None):
            logger.debug("_ofind(oname=%r, namespaces=%r)", oname, namespaces)
            if namespaces is None:
                namespaces = _ipython_namespaces(ip)
            if is_identifier(oname, dotted=True):
                auto_import(str(oname), [ns for nsname,ns in namespaces][::-1])
            result = orig_ofind(oname, namespaces=namespaces)
            return result
        ip._ofind = wrapped_ofind
    else:
        logger.debug("Couldn't install ofind hook for IPython version %s",
                     IPython.__version__)

    if hasattr(ip, 'ast_transformers'):
        # IPython >= 1.0+: Hook ast_transformers.
        ip.ast_transformers.append(_AutoImporter_ast_transformer())
    elif hasattr(ip, 'compile') and hasattr(ip.compile, 'ast_parse'):
        # IPython < 1.0: Hook the AST parse step.
        orig_ast_parse = ip.compile.ast_parse
        def wrapped_ast_parse(source, *args, **kwargs):
            logger.debug("ast_parse %r", source)
            ast = orig_ast_parse(source, *args, **kwargs)
            auto_import(ast, get_global_namespaces())
            return ast
        ip.compile.ast_parse = wrapped_ast_parse
    elif hasattr(ip, 'prefilter_manager'):
        # IPython < 1.0: Add prefilter manager.
        ip.prefilter_manager.register_checker(_AutoImporter_prefilter_checker())
    else:
        logger.debug("Couldn't install a line transformer for IPython version %s", IPython.__version__)

    # Install a tab-completion hook.
    #
    # There are a few different places within IPython we can consider hooking:
    #   * ip.completer.custom_completers / ip.set_hook("complete_command")
    #   * ip.completer.python_matches
    #   * ip.completer.global_matches
    #   * ip.completer.attr_matches
    #   * ip.completer.python_func_kw_matches
    #
    # The "custom_completers" list, which set_hook("complete_command")
    # manages, is not useful because that only works for specific commands.
    # (A "command" refers to the first word on a line, such as "cd".)
    #
    # We choose to hook global_matches() and attr_matches(), which are called
    # to enumerate global and non-global attribute symbols respectively.
    # (python_matches() calls these two.  We hook global_matches() and
    # attr_matches() instead of python_matches() because a few other functions
    # call global_matches/attr_matches directly.)
    #
    if hasattr(ip, "Completer"):
        completer = ip.Completer
        completer.global_matches = _complete_symbol_during_prompt
        completer.attr_matches   = _complete_symbol_during_prompt
        # TODO: also hook completer.python_func_kw_matches
    else:
        logger.debug("Couldn't install completion hook for IPython version %s", IPython.__version__)
