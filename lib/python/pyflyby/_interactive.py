# pyflyby/_interactive.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __builtin__
import ast
import inspect
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
from   pyflyby._parse           import PythonBlock
from   pyflyby._util            import (CwdCtx, FunctionWithGlobals, NullCtx,
                                        advise, memoize)


if False:
    __original__ = None # for pyflakes


# TODO: also support arbitrary code (in the form of a lambda and/or
# assignment) as new way to do "lazy" creations, e.g. foo = a.b.c(d.e+f.g())

# TODO: pass the ipython shell parameter ip all the way down.  Then we don't
# need to memoize get_ipython_safe().


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
    Install the call to 'pyflyby.enable_auto_importer()' to the default
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
        "pyflyby.enable_auto_importer()\n"
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


def _ipython_in_multiline(ip):
    """
    Return C{False} if the user has entered only one line of input so far,
    including the current line, or C{True} if it is the second or later line.

    @rtype:
      C{bool}
    """
    if hasattr(ip, "input_splitter"):
        # IPython 0.11+.  Tested with IPython 0.11, 0.12, 0.13, 1.0, 1.2, 2.1.
        return bool(ip.input_splitter.source)
    elif hasattr(ip, "buffer"):
        # IPython 0.10
        return bool(ip.buffer)
    else:
        # IPython version too old or too new?
        return False


def InterceptPrintsDuringPromptCtx(ip):
    """
    Decorator that hooks our logger so that:
      1. Before the first print, if any, print an extra newline.
      2. Upon context exit, if any lines were printed, redisplay the prompt.
    """
    if not ip:
        return NullCtx()
    readline = ip.readline
    if not hasattr(readline, "redisplay"):
        # May be IPython Notebook.
        return NullCtx()
    redisplay = readline.redisplay
    get_prompt = None
    if hasattr(ip, "prompt_manager"):
        # IPython >= 0.12 (known to work including up to 1.2, 2.1)
        prompt_manager = ip.prompt_manager
        def get_prompt_ipython_012():
            if _ipython_in_multiline(ip):
                return prompt_manager.render("in2")
            else:
                return ip.separate_in + prompt_manager.render("in")
        get_prompt = get_prompt_ipython_012
    elif hasattr(ip.hooks, "generate_prompt"):
        # IPython 0.10, 0.11
        generate_prompt = ip.hooks.generate_prompt
        def get_prompt_ipython_010():
            if _ipython_in_multiline(ip):
                return generate_prompt(True)
            else:
                if hasattr(ip, "outputcache"):
                    # IPython 0.10 (but not 0.11+):
                    # Decrement the prompt_count since it otherwise
                    # auto-increments.  (It's hard to avoid the
                    # auto-increment as it happens as a side effect of
                    # __str__!)
                    ip.outputcache.prompt_count -= 1
                return generate_prompt(False)
        get_prompt = get_prompt_ipython_010
    else:
        # Too old or too new IPython version?
        return NullCtx()
    def pre():
        sys.stdout.write("\n")
        sys.stdout.flush()
    def post():
        # Re-display the current line.
        prompt = get_prompt()
        prompt = prompt.replace("\x01", "").replace("\x02", "")
        line = readline.get_line_buffer()[:readline.get_endidx()]
        sys.stdout.write(prompt + line)
        redisplay()
        sys.stdout.flush()
    return logger.HookCtx(pre=pre, post=post)


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



def get_global_namespaces(ip):
    """
    Get the global interactive namespaces.

    @param ip:
      IPython shell or C{None} for non-IPython, as returned by
      get_ipython_safe().
    @rtype:
      C{list} of C{dict}
    """
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
        try:
            limit_to__all__ = ip.Completer.limit_to__all__
        except AttributeError:
            limit_to__all__ = False
        if limit_to__all__ and hasattr(obj, '__all__'):
            words = getattr(obj, '__all__')
        elif "IPython.core.error" in sys.modules:
            from IPython.utils import generics
            from IPython.utils.dir2 import dir2
            from IPython.core.error import TryNext
            words = dir2(obj)
            try:
                words = generics.complete_object(obj, words)
            except TryNext:
                pass
        else:
            words = dir(obj)
    return [w for w in words if isinstance(w, basestring)]


class _AutoImporter(object):
    """
    Auto importer enable state.
    """

    def __init__(self):
        self._disablers = []
        self._enabled = False
        self._errored = False
        self._ip = None
        self._ast_transformer = None

    def enable(self, even_if_previously_errored=False):
        """
        Turn on the auto-importer in the current IPython session.
        """
        # Check if already enabled.  If so, silently do nothing.
        if self._enabled:
            return
        # Check if previously errored.
        if self._errored:
            if even_if_previously_errored:
                self._errored = False
            else:
                # Be conservative: Once we've had problems, don't try again
                # this session.  Exceptions in the interactive loop can be
                # annoying to deal with.
                logger.warning(
                    "Not reattempting to enable auto importer after earlier "
                    "error")
                return
        self._errored = False
        import IPython
        logger.debug("Enabling auto importer for IPython version %s",
                     IPython.__version__)
        # TODO: advise IPython.kernel.launcher.make_ipkernel_cmd (even if
        # get_ipython_safe() returns None)
        # TODO: if no ipython shell yet then delay until there is, instead of
        # doing nothing
        ip = get_ipython_safe()
        if not ip:
            return
        self._ip = ip
        if IPython.__version__.startswith("0.10"):
            # Yuck.  IPython might not be ready to hook yet because we're
            # called from the config phase, and certain stuff (like Completer)
            # is set up in post-config.  Delay ourselves until after
            # post_config_initialization.
            # Kludge: post_config_initialization() sets ip.rl_next_input=None,
            # so assume that if it's not set, then post_config_initialization
            # hasn't been run yet.
            if not hasattr(ip, "rl_next_input"):
                logger.debug("Postponing remaining steps until after "
                             "IPython post-config initialization")
                @advise(ip.post_config_initialization)
                def post_config_enable_auto_importer():
                    post_config_enable_auto_importer.unadvise()
                    __original__()
                    if not hasattr(ip, "rl_next_input"):
                        # Post-config initialization failed?
                        return
                    self._safe_call(self._enable_shell_hooks)
                self._disablers.append(post_config_enable_auto_importer.unadvise)
                return
        # *** Enable ***.
        self._safe_call(self._enable_shell_hooks)

    def _enable_shell_hooks(self):
        """
        Enable hooks to run auto_import before code execution.
        """
        # Check again in case this was registered delayed
        if self._enabled or self._errored:
            return
        # Notes on why we hook what we hook:
        #
        # There are many different places within IPython we can consider
        # hooking/advising, depending on the version:
        #   * ip.input_transformer_manager.logical_line_transforms
        #   * ip.compile.ast_parse (IPython 0.12+)
        #   * ip.run_ast_nodes (IPython 0.11+)
        #   * ip.runsource (IPython 0.10)
        #   * ip.prefilter_manager.checks
        #   * ip.prefilter_manager.handlers["auto"]
        #   * ip.ast_transformers
        #   * ip.hooks['pre_run_code_hook']
        #   * ip._ofind
        #
        # We choose to hook in two places: (1) _ofind and (2)
        # ast_transformers.  The motivation follows.  We want to handle
        # auto-imports for all of these input cases:
        #   (1) "foo.bar"
        #   (2) "arbitrarily_complicated_stuff((lambda: foo.bar)())"
        #   (3) "foo.bar?", "foo.bar??" (pinfo/pinfo2)
        #   (4) "foo.bar 1, 2" => "foo.bar(1, 2)" (autocall)
        #
        # Case 1 is the easiest and can be handled by nearly any method.  Case
        # 2 must be done either as a prefilter or as an AST transformer.
        # Cases 3 and 4 must be done either as an input line transformer or by
        # monkey-patching _ofind, because by the time the
        # prefilter/ast_transformer is called, it's too late.
        #
        # To handle case 2, we use an AST transformer (for IPython > 1.0), or
        # monkey-patch one of the compilation steps (ip.compile for IPython
        # 0.10 and ip.run_ast_nodes for IPython 0.11-0.13).
        # prefilter_manager.checks() is the "supported" way to add a
        # pre-execution hook, but it only works for single lines, not for
        # multi-line cells.  (There is no explanation in the IPython source
        # for why prefilter hooks are seemingly intentionally skipped for
        # multi-line cells).
        #
        # To handle cases 3/4 (pinfo/autocall), we choose to advise _ofind.
        # This is a private function that is called by both pinfo and autocall
        # code paths.  (Alternatively, we could have added something to the
        # logical_line_transforms.  The downside of that is that we would need
        # to re-implement all the parsing perfectly matching IPython.
        # Although monkey-patching is in general bad, it seems the lesser of
        # the two evils in this case.)
        #
        # Since we have two invocations of auto_import(), case 1 is
        # handled twice.  That's fine, because it runs quickly.
        logger.debug("Enabling IPython shell hooks")
        self._enable_ofind_hook()
        self._enable_ast_hook()
        self._enable_timeit_hook()
        self._enable_prun_hook()
        self._enable_completion_hook()
        self._enable_run_hook()
        self._enable_ipython_bugfixes()
        # Completed.  (At least we did what we could, and no exceptions.)
        self._enabled = True
        return True

    def _enable_ofind_hook(self):
        """
        Enable a hook of _ofind(), which is used for pinfo, autocall, etc.
        """
        ip = self._ip
        # Advise _ofind.
        if hasattr(ip, "_ofind"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @advise(ip._ofind)
            def ofind_with_autoimport(oname, namespaces=None):
                logger.debug("_ofind(oname=%r, namespaces=%r)", oname, namespaces)
                is_multiline = False
                if hasattr(ip, "buffer"):
                    # In IPython 0.10, _ofind() gets called for each line of a
                    # multiline input.  Skip them.
                    is_multiline = len(ip.buffer) > 0
                if namespaces is None:
                    namespaces = _ipython_namespaces(ip)
                if not is_multiline and is_identifier(oname, dotted=True):
                    self.auto_import(str(oname), [ns for nsname,ns in namespaces][::-1])
                result = __original__(oname, namespaces=namespaces)
                return result
            self._disablers.append(ofind_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable ofind hook")

    def _enable_ast_hook(self):
        """
        Enable a hook somewhere in the source => parsed AST => compiled code
        pipeline.
        """
        ip = self._ip
        # Register an AST transformer.
        if hasattr(ip, 'ast_transformers'):
            logger.debug("Registering an ast_transformer")
            # First choice: register a formal ast_transformer.
            # Tested with IPython 1.0, 1.2, 2.0, 2.3.
            class _AutoImporter_ast_transformer(object):
                """
                A NodeVisitor-like wrapper around C{auto_import_for_ast} for
                the API that IPython 1.x's C{ast_transformers} needs.
                """
                def visit(self_, node):
                    # We don't actually transform the node; we just use
                    # the ast_transformers mechanism instead of the
                    # prefilter mechanism as an optimization to avoid
                    # re-parsing the text into an AST.
                    #
                    # We use raise_on_error=False to avoid propagating any
                    # exceptions here.  That would cause IPython to try to
                    # remove the ast_transformer.  On error, we've already
                    # done that ourselves.
                    logger.debug("_AutoImporter_ast_transformer.visit()")
                    self.auto_import(node, raise_on_error=False)
                    return node
            self._ast_transformer = t = _AutoImporter_ast_transformer()
            ip.ast_transformers.append(t)
            def unregister_ast_transformer():
                try:
                    ip.ast_transformers.remove(t)
                except ValueError:
                    logger.info(
                        "Couldn't remove ast_transformer hook - already gone?")
                self._ast_transformer = None
            self._disablers.append(unregister_ast_transformer)
        elif hasattr(ip, "run_ast_nodes"):
            # Second choice: advise the run_ast_nodes() function.  Tested with
            # IPython 0.11, 0.12, 0.13.  This is the most robust way available
            # for those versions.
            # (ip.compile.ast_parse also works in IPython 0.12-0.13; no major
            # flaw, but might as well use the same mechanism that works in
            # 0.11.)
            @advise(ip.run_ast_nodes)
            def run_ast_nodes_with_autoimport(nodelist, *args, **kwargs):
                logger.debug("run_ast_nodes")
                ast_node = ast.Module(nodelist)
                self.auto_import(ast_node)
                return __original__(nodelist, *args, **kwargs)
            self._disablers.append(run_ast_nodes_with_autoimport.unadvise)
        elif hasattr(ip, 'compile'):
            # Third choice: Advise ip.compile.
            # Tested with IPython 0.10.
            # We don't hook prefilter because that gets called once per line,
            # not per multiline code.
            # We don't hook runsource because that gets called incrementally
            # with partial multiline source until the source is complete.
            @advise((ip, "compile"))
            def compile_with_autoimport(source, filename="<input>",
                                        symbol="single"):
                result = __original__(source, filename, symbol)
                if result is None:
                    # The original ip.compile is an instance of
                    # codeop.CommandCompiler.  CommandCompiler.__call__
                    # returns None if the source is a possibly incomplete
                    # multiline block of code.  In that case we don't
                    # autoimport yet.
                    pass
                else:
                    # Got full code that our caller, runsource, will execute.
                    self.auto_import(source)
                return result
            self._disablers.append(compile_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable parse hook")

    def _enable_timeit_hook(self):
        """
        Enable a hook so that %timeit will autoimport.
        """
        # For IPython 1.0+, the ast_transformer takes care of it.
        if self._ast_transformer:
            return
        # Otherwise, we advise timeit and "letf"[*] the compile() builtin
        # within it.
        # [*] "letf" in Common Lisp roughly means temporarily change one function
        # within another function
        ip = self._ip
        if hasattr(ip, 'magics_manager'):
            # Tested with IPython 0.13.  (IPython 1.0+ also has
            # magics_manager, but for those versions, ast_transformer takes
            # care of timeit.)
            line_magics = ip.magics_manager.magics['line']
            @advise((line_magics, 'timeit'))
            def timeit_with_autoimport(*args, **kwargs):
                logger.debug("timeit_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            self._disablers.append(timeit_with_autoimport.unadvise)
        elif hasattr(ip, 'magic_timeit'):
            # Tested with IPython 0.10, 0.11, 0.12
            @advise(ip.magic_timeit)
            def magic_timeit_with_autoimport(*args, **kwargs):
                logger.debug("timeit_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            self._disablers.append(magic_timeit_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable timeit hook")

    def _enable_prun_hook(self):
        ip = self._ip
        if hasattr(ip, 'magics_manager'):
            # Tested with IPython 1.0, 1.1, 1.2, 2.0, 2.1, 2.2, 2.3.
            line_magics = ip.magics_manager.magics['line']
            execmgr = line_magics['prun'].im_self
            if hasattr(execmgr, "_run_with_profiler"):
                @advise(execmgr._run_with_profiler)
                def run_with_profiler_with_autoimport(code, opts, namespace):
                    logger.debug("run_with_profiler_with_autoimport()")
                    self.auto_import(code, [namespace])
                    return __original__(code, opts, namespace)
                self._disablers.append(run_with_profiler_with_autoimport.unadvise)
            else:
                # Tested with IPython 0.13.
                class ProfileFactory_with_autoimport(object):
                    def Profile(self_, *args):
                        import profile
                        p = profile.Profile()
                        @advise(p.runctx)
                        def runctx_with_autoimport(cmd, globals, locals):
                            self.auto_import(cmd, [globals, locals])
                            return __original__(cmd, globals, locals)
                        return p
                @advise((line_magics, 'prun'))
                def prun_with_autoimport(*args, **kwargs):
                    logger.debug("prun_with_autoimport()")
                    wrapped = FunctionWithGlobals(
                        __original__, profile=ProfileFactory_with_autoimport())
                    return wrapped(*args, **kwargs)
                self._disablers.append(prun_with_autoimport.unadvise)
        elif hasattr(ip, "magic_prun"):
            # Tested with IPython 0.10, 0.11, 0.12.
            class ProfileFactory_with_autoimport(object):
                def Profile(self_, *args):
                    import profile
                    p = profile.Profile()
                    @advise(p.runctx)
                    def runctx_with_autoimport(cmd, globals, locals):
                        self.auto_import(cmd, [globals, locals])
                        return __original__(cmd, globals, locals)
                    return p
            @advise(ip.magic_prun)
            def magic_prun_with_autoimport(*args, **kwargs):
                logger.debug("magic_prun_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, profile=ProfileFactory_with_autoimport())
                return wrapped(*args, **kwargs)
            self._disablers.append(magic_prun_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable prun hook")

    def _enable_completion_hook(self):
        """
        Enable a tab-completion hook.
        """
        # There are a few different places within IPython we can consider
        # hooking/advising:
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
        # We choose to advise global_matches() and attr_matches(), which are
        # called to enumerate global and non-global attribute symbols
        # respectively.  (python_matches() calls these two.  We advise
        # global_matches() and attr_matches() instead of python_matches()
        # because a few other functions call global_matches/attr_matches
        # directly.)
        ip = self._ip
        if hasattr(ip, "Completer"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @advise(ip.Completer.global_matches)
            def global_matches_with_autoimport(fullname):
                return self.complete_symbol(fullname, on_error=__original__)
            @advise(ip.Completer.attr_matches)
            def attr_matches_with_autoimport(fullname):
                return self.complete_symbol(fullname, on_error=__original__)
            self._disablers.append(global_matches_with_autoimport.unadvise)
            self._disablers.append(attr_matches_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable completion hook")

    def _enable_run_hook(self):
        """
        Enable a hook so that %run will autoimport.
        """
        ip = self._ip
        if hasattr(ip, "safe_execfile"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @advise(ip.safe_execfile)
            def safe_execfile_with_autoimport(filename,
                                              globals=None, locals=None,
                                              **kwargs):
                logger.debug("safe_execfile %r", filename)
                if globals is None:
                    globals = {}
                if locals is None:
                    locals = globals
                namespaces = [globals, locals]
                try:
                    block = PythonBlock(Filename(filename))
                    ast_node = block.ast_node
                    self.auto_import(ast_node, namespaces)
                except Exception as e:
                    logger.error("%s: %s", type(e).__name__, e)
                return __original__(filename, *namespaces, **kwargs)
            self._disablers.append(safe_execfile_with_autoimport.unadvise)
        else:
            logger.debug("Couldn't enable execfile hook")

    def _enable_ipython_bugfixes(self):
        """
        Enable some advice that's actually just fixing bugs in IPython.
        """
        # IPython 2.x on Python 2.x has a bug where 'run -n' doesn't work
        # because it uses Unicode for the module name.  This is a bug in
        # IPython itself ("run -n" is plain broken for ipython-2.x on
        # python-2.x); we patch it here.
        ip = get_ipython_safe()
        if (sys.version_info < (3,) and
            hasattr(ip, "new_main_mod") and
            inspect.getargspec(ip.new_main_mod).args == ["self","filename","modname"]):
            @advise(ip.new_main_mod)
            def new_main_mod_fix_str(filename, modname):
                if type(modname) is unicode:
                    modname = str(modname)
                return __original__(filename, modname)
            self._disablers.append(new_main_mod_fix_str.unadvise)

    def disable(self):
        """
        Turn off auto-importer in the current IPython session.
        """
        self._enabled = False
        while self._disablers:
            f = self._disablers.pop(-1)
            f()

    def _safe_call(self, function, *args, **kwargs):
        on_error = kwargs.pop("on_error", None)
        raise_on_error = kwargs.pop("raise_on_error", "if_debug")
        if self._errored:
            # If we previously errored, then we should already have
            # unregistered the hook that led to here.  However, in some corner
            # cases we can get called one more time.  If so, go straight to
            # the on_error case.
            pass
        else:
            try:
                return function(*args, **kwargs)
            except Exception as e:
                # Something went wrong.  Remember that we've had a problem.
                self._errored = True
                logger.error("%s: %s", type(e).__name__, e)
                if not logger.debug_enabled:
                    logger.info(
                        "Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.")
                logger.warning("Disabling pyflyby auto importer.")
                # Disable everything.  If something's broken, chances are
                # other stuff is broken too.
                try:
                    self.disable()
                except Exception as e2:
                    logger.error("Error trying to disable: %s: %s",
                                 type(e2).__name__, e2)
                # Raise or print traceback in debug mode.
                if raise_on_error == True:
                    raise
                elif raise_on_error == 'if_debug':
                    if logger.debug_enabled:
                        if type(e) == SyntaxError:
                            # The traceback for SyntaxError tends to get
                            # swallowed, so print it out now.
                            import traceback
                            traceback.print_exc()
                        raise
                elif raise_on_error == False:
                    if logger.debug_enabled:
                        import traceback
                        traceback.print_exc()
                else:
                    logger.error("internal error: invalid raise_on_error=%r",
                                 raise_on_error)
        # Return what user wanted to in case of error.
        if on_error:
            return on_error(*args, **kwargs)
        else:
            return None # just to be explicit

    def auto_import(self, arg, namespaces=None,
                    raise_on_error='if_debug', on_error=None):
        if namespaces is None:
            namespaces = get_global_namespaces(self._ip)
        return self._safe_call(
            auto_import, arg, namespaces,
            raise_on_error=raise_on_error, on_error=on_error)

    def complete_symbol(self, fullname,
                        raise_on_error='if_debug', on_error=None):
        with InterceptPrintsDuringPromptCtx(self._ip):
            namespaces = get_global_namespaces(self._ip)
            if on_error is not None:
                on_error1 = lambda fullname, namespaces: on_error(fullname)
            else:
                on_error1 = None
            return self._safe_call(
                complete_symbol, fullname, namespaces,
                raise_on_error=raise_on_error, on_error=on_error1)

    def compile_with_autoimport(self, src, filename, mode, flags=0):
        logger.debug("compile_with_autoimport(%r)", src)
        ast_node = compile(src, filename, mode, flags|ast.PyCF_ONLY_AST,
                           dont_inherit=True)
        self.auto_import(ast_node)
        if flags & ast.PyCF_ONLY_AST:
            return ast_node
        else:
            return compile(ast_node, filename, mode, flags, dont_inherit=True)


_auto_importer = _AutoImporter()

def enable_auto_importer():
    """
    Turn on the auto-importer in the current IPython session.
    """
    # This is a separate function instead of just an assignment, for the sake
    # of documentation, introspection, import into package namespace.
    _auto_importer.enable()


def disable_auto_importer():
    """
    Turn off the auto-importer in the current IPython session.
    """
    _auto_importer.disable()
