# pyflyby/_interactive.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import __builtin__
import ast
import inspect
import os
import re
import subprocess
import sys

from   pyflyby._autoimp         import (auto_import, interpret_namespaces,
                                        load_symbol)
from   pyflyby._file            import Filename, atomic_write_file, read_file
from   pyflyby._idents          import is_identifier
from   pyflyby._importdb        import ImportDB
from   pyflyby._log             import logger
from   pyflyby._modules         import ModuleHandle
from   pyflyby._parse           import PythonBlock
from   pyflyby._util            import (Aspect, CwdCtx, FunctionWithGlobals,
                                        NullCtx, advise, indent)


if False:
    __original__ = None # for pyflakes


# TODO: also support arbitrary code (in the form of a lambda and/or
# assignment) as new way to do "lazy" creations, e.g. foo = a.b.c(d.e+f.g())


def _get_or_create_ipython_terminal_app():
    """
    Create/get the singleton IPython terminal application.

    @rtype:
      C{TerminalIPythonApp}
    """
    import IPython
    # The following has been tested on IPython 1.0, 1.2, 2.0, 2.1, 2.2, 2.3.
    try:
        TerminalIPythonApp = IPython.terminal.ipapp.TerminalIPythonApp
    except AttributeError:
        pass
    else:
        return TerminalIPythonApp.instance()
    # The following has been tested on IPython 0.11, 0.12, 0.13.
    try:
        TerminalIPythonApp = IPython.frontend.terminal.ipapp.TerminalIPythonApp
    except AttributeError:
        pass
    else:
        return TerminalIPythonApp.instance()
    # The following has been tested on IPython 0.10.
    if hasattr(IPython, "ipapi"):
        return _IPython010TerminalApplication.instance()
    raise RuntimeError(
        "Couldn't get TerminalIPythonApp class.  "
        "Is your IPython version too old (or too new)?  "
        "IPython.__version__=%r" % (IPython.__version__))


class _IPython010TerminalApplication(object):
    """
    Shim class that mimics IPython 0.11+ application classes, for use in
    IPython 0.10.
    """

    # IPython.ipapi.launch_instance() => IPython.Shell.start() creates an
    # instance of "IPShell".  IPShell has an attribute named "IP" which is an
    # "InteractiveShell".

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is not None:
            self = cls._instance
            self.init_shell()
            return self
        import IPython
        if not hasattr(IPython, "ipapi"):
            raise RuntimeError("Inappropriate version of IPython %r"
                               % (IPython.__version__,))
        self = cls._instance = cls()
        self.init_shell()
        return self

    def init_shell(self):
        import IPython
        ipapi = IPython.ipapi.get()                # IPApi instance
        if ipapi is not None:
            self.shell = ipapi.IP                  # InteractiveShell instance
        else:
            self.shell = None

    def initialize(self, argv=None):
        import IPython
        logger.debug("Creating IPython 0.10 session")
        self._session = IPython.ipapi.make_session() # IPShell instance
        self.init_shell()
        assert self._session is not None

    def start(self):
        self._session.mainloop()


def _get_or_create_ipython_kernel_app():
    """
    Create/get the singleton IPython kernel application.

    @rtype:
      C{callable}
    @return:
      The function that can be called to start the kernel application.
    """
    import IPython
    # The following has been tested on IPython 1.0, 1.2, 2.0, 2.1, 2.2, 2.3
    try:
        from IPython.kernel.zmq.kernelapp import IPKernelApp
    except ImportError:
        pass
    else:
        return IPKernelApp.instance()
    # The following has been tested on IPython 0.12, 0.13
    try:
        from IPython.zmq.ipkernel import IPKernelApp
    except ImportError:
        pass
    else:
        return IPKernelApp.instance()
    raise RuntimeError(
        "Couldn't get IPKernelApp class.  "
        "Is your IPython version too old (or too new)?  "
        "IPython.__version__=%r" % (IPython.__version__))


def start_ipython_with_autoimporter(argv=None):
    """
    Start IPython with autoimporter enabled.
    """
    app = _get_or_create_ipython_terminal_app()
    return _initialize_and_start_app_with_autoimporter(app, argv)


def start_ipython_kernel_with_autoimporter(argv=None):
    """
    Start IPython kernel with autoimporter enabled.
    """
    app = _get_or_create_ipython_kernel_app()
    return _initialize_and_start_app_with_autoimporter(app, argv)


def _initialize_and_start_app_with_autoimporter(app, argv):
    """
    Initialize and start an IPython app, with autoimporting enabled.

    @type app:
      L{BaseIPythonApplication}
    """
    AutoImporter(app).enable()
    app.initialize(argv)
    return app.start()


def run_ipython_line_magic(arg):
    """
    Run IPython magic command.
    If necessary, start an IPython terminal app to do so.
    """
    import IPython
    if not arg.startswith("%"):
        arg = "%" + arg
    app = _get_or_create_ipython_terminal_app()
    AutoImporter(app).enable()
    # TODO: only initialize if not already initialized.
    app.initialize([])
    ip = app.shell
    if hasattr(ip, "magic"):
        # IPython 0.11+.
        # The following has been tested on IPython 0.11, 0.12, 0.13, 1.0, 1.2,
        # 2.0, 2.1, 2.2, 2.3.
        # TODO: may want to wrap in one or two layers of dummy functions to make
        # sure run_line_magic() doesn't inspect our locals.
        return ip.magic(arg)
    elif hasattr(ip, "runlines"):
        # IPython 0.10
        return ip.runlines(arg)
    else:
        raise RuntimeError(
            "Couldn't run IPython magic.  "
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

    This makes all "ipython" sessions behave like "autoipython", i.e. start
    with the autoimporter already enabled.
    """
    import IPython
    # The following has been tested on IPython 0.12, 0.13, 1.0, 1.2, 2.0, 2.1,
    # 2.2, 2.3.
    try:
        IPython.core.profiledir.ProfileDir.startup_dir
    except AttributeError:
        pass
    else:
        _install_in_ipython_startup_file_012()
        return
    # The following has been tested on IPython 0.11.
    try:
        IPython.core.profiledir.ProfileDir
    except AttributeError:
        pass
    else:
        _install_in_ipython_startup_file_011()
        return
    try:
        IPython.genutils.get_ipython_dir
    except AttributeError:
        pass
    else:
        _install_in_ipython_startup_file_010()
        return
    raise RuntimeError(
        "Couldn't install pyflyby autoimporter in IPython.  "
        "Is your IPython version too old (or too new)?  "
        "IPython.__version__=%r" % (IPython.__version__))


def _generate_enabler_code():
    """
    Generate code for enabling the auto importer.

    @rtype:
      C{str}
    """
    funcdef = (
        "import pyflyby\n"
        "pyflyby.enable_auto_importer()\n"
    )
    # Check whether we need to include the path in sys.path, and if so, add
    # that to the contents.
    import pyflyby
    pyflyby_path = pyflyby.__path__[0]
    if not _python_can_import_pyflyby(pyflyby_path):
        path_entry = os.path.dirname(os.path.realpath(pyflyby_path))
        assert _python_can_import_pyflyby(pyflyby_path, path_entry)
        funcdef = (
            "import sys\n"
            "saved_sys_path = sys.path[:]\n"
            "try:\n"
            "    sys.path.insert(0, %r)\n" % (path_entry,) +
            indent(funcdef, "    ") +
            "finally:\n"
            "    sys.path = saved_sys_path\n"
        )
    # Wrap the code in a temporary function, call it, then delete the
    # function.  This avoids polluting the user's global namespace.  Although
    # the global name "pyflyby" will almost always end up meaning the module
    # "pyflyby" anyway, if the user types it, there's still value in not
    # polluting the namespace in case something enumerates over globals().
    # For the function name we use a name that's unlikely to be used by the
    # user.
    contents = (
        "def __pyflyby_enable_auto_importer_60321389():\n" +
        indent(funcdef, "    ") +
        "__pyflyby_enable_auto_importer_60321389()\n"
        "del __pyflyby_enable_auto_importer_60321389\n"
    )
    return contents


def _install_in_ipython_startup_file_012():
    """
    Implementation of L{install_in_ipython_startup_file} for IPython 0.12+.
    Tested with IPython 0.12, 0.13, 1.0, 1.2, 2.0, 2.1, 2.2, 2.3.
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
    argv = sys.argv[:]
    argv[0] = os.path.realpath(argv[0])
    argv = ' '.join(argv)
    header = (
        "# File: {fn}\n"
        "#\n"
        "# Generated by {argv}\n"
        "#\n"
        "# This file causes IPython to enable the Pyflyby Auto Importer.\n"
        "#\n"
        "# To uninstall, just delete this file.\n"
        "#\n"
    ).format(**locals())
    contents = header + _generate_enabler_code()
    logger.info("Installing pyflyby auto importer in your IPython startup")
    logger.info("Writing to %s:\n%s", fn, contents)
    atomic_write_file(fn, contents)


def _install_in_ipython_startup_file_011():
    """
    Implementation of L{install_in_ipython_startup_file} for IPython 0.11.
    """
    import IPython
    ipython_dir = Filename(IPython.utils.path.get_ipython_dir())
    fn = ipython_dir / "profile_default" / "ipython_config.py"
    if not fn.exists:
        raise RuntimeError(
            "Couldn't find IPython startup file.  Tried %s" % (fn,))
    old_contents = read_file(fn).joined
    if re.search(r"^ *(pyflyby[.])?enable_auto_importer[(][)]", old_contents, re.M):
        logger.info("Doing nothing, because already installed in %s", fn)
        return
    header = (
        "\n"
        "\n"
        "#\n"
        "# Enable the Pyflyby Auto Importer.\n"
    )
    new_contents = header + _generate_enabler_code()
    contents = old_contents.rstrip() + new_contents
    logger.info("Installing pyflyby auto importer in your IPython startup")
    logger.info("Appending to %s:\n%s", fn, new_contents)
    atomic_write_file(fn, contents)


def _install_in_ipython_startup_file_010():
    """
    Implementation of L{install_in_ipython_startup_file} for IPython 0.10.
    """
    import IPython
    ipython_dir = Filename(IPython.genutils.get_ipython_dir())
    fn = ipython_dir / "ipy_user_conf.py"
    if not fn.exists:
        raise RuntimeError(
            "Couldn't find IPython config file.  Tried %s" % (fn,))
    old_contents = read_file(fn).joined
    if re.search(r"^ *(pyflyby[.])?enable_auto_importer[(][)]", old_contents, re.M):
        logger.info("Doing nothing, because already installed in %s", fn)
        return
    header = (
        "\n"
        "\n"
        "#\n"
        "# Enable the Pyflyby Auto Importer.\n"
    )
    new_contents = header + _generate_enabler_code()
    contents = old_contents.rstrip() + new_contents
    logger.info("Installing pyflyby auto importer in your IPython startup")
    logger.info("Appending to %s:\n%s", fn, new_contents)
    atomic_write_file(fn, contents)


def _ipython_in_multiline(ip):
    """
    Return C{False} if the user has entered only one line of input so far,
    including the current line, or C{True} if it is the second or later line.

    @type ip:
      C{InteractiveShell}
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

    @type ip:
      C{InteractiveShell}
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


class NoIPythonAppError(Exception):
    pass


def _get_ipython_app():
    """
    Get an IPython application instance, if we are inside an IPython session.

    If there isn't already an IPython application, raise an exception; don't
    create one.

    If there is a subapp, return it.

    @rtype:
      L{BaseIPythonApplication}
    """
    try:
        IPython = sys.modules['IPython']
    except KeyError:
        # The 'IPython' module isn't already loaded, so we're not in an
        # IPython session.  Don't import it.
        raise NoIPythonAppError(
            "No active IPython application (IPython not even imported yet)")
    # The following has been tested on IPython 0.11, 0.12, 0.13, 1.0, 1.2,
    # 2.0, 2.1, 2.2, 2.3.
    try:
        App = IPython.core.application.BaseIPythonApplication
    except AttributeError:
        pass
    else:
        app = App._instance
        if app is None:
            raise NoIPythonAppError("No active IPython application")
        if app.subapp is not None:
            return app.subapp
        else:
            return app
    # The following has been tested on IPython 0.10.
    if hasattr(IPython, "ipapi"):
        return _IPython010TerminalApplication.instance()
    raise NoIPythonAppError(
        "Could not figure out how to get active IPython application for IPython version %s"
        % (IPython.__version__,))


def _ipython_namespaces(ip):
    """
    Return the (global) namespaces used for IPython.

    The ordering follows IPython convention of most-local to most-global.

    @type ip:
      C{InteractiveShell}
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

    @type ip:
      C{InteractiveShell}
    @param ip:
      IPython shell or C{None} to assume not in IPython.
    @rtype:
      C{list} of C{dict}
    """
    if ip:
        return [ns for nsname, ns in _ipython_namespaces(ip)][::-1]
    else:
        import __main__
        return [__builtin__.__dict__, __main__.__dict__]


def complete_symbol(fullname, namespaces, db=None, autoimported=None, ip=None):
    """
    Enumerate possible completions for C{fullname}.

    Includes globals and auto-importable symbols.

      >>> complete_symbol("threadi", [{}])                # doctest:+ELLIPSIS
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
    @type ip:
      C{InteractiveShell}
    @param ip:
      IPython shell instance if in IPython; C{None} to assume not in IPython.
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
            parent = load_symbol(pname, namespaces, autoimport=True, db=db,
                                 autoimported=autoimported)
        except AttributeError:
            # Even after attempting auto-import, the symbol is still
            # unavailable.  Nothing to complete.
            logger.debug("complete_symbol(%r): couldn't load symbol %r", fullname, pname)
            return []
        results = set()
        # Add current attribute members.
        results.update(_list_members_for_completion(parent, ip))
        # Is the parent a package/module?
        if sys.modules.get(pname, Ellipsis) is parent and parent.__name__ == pname:
            # Add known_imports entries from the database.
            results.update(known.member_names.get(pname, []))
            # Get the module handle.  Note that we use ModuleHandle() on the
            # *name* of the module (C{pname}) instead of the module instance
            # (C{parent}).  Using the module instance normally works, but
            # breaks if the module hackily replaced itself with a pseudo
            # module (e.g. https://github.com/josiahcarlson/mprop).
            pmodule = ModuleHandle(pname)
            # Add importable submodules.
            results.update([m.name.parts[-1] for m in pmodule.submodules])
        results = sorted([r for r in results if r.startswith(attrname)])
        results = ["%s.%s" % (pname, r) for r in results]
    return results


def _list_members_for_completion(obj, ip):
    """
    Enumerate the existing member attributes of an object.
    This emulates the regular Python/IPython completion items.

    It does not include not-yet-imported submodules.

    @param obj:
      Object whose member attributes to enumerate.
    @rtype:
      C{list} of C{str}
    """
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


class _EnableState(object):
    DISABLING = "DISABLING"
    DISABLED  = "DISABLED"
    ENABLING  = "ENABLING"
    ENABLED   = "ENABLED"


class AutoImporter(object):
    """
    Auto importer enable state.

    The state is attached to an IPython "application".
    """

    def __new__(cls, arg):
        """
        Get the AutoImporter for C{app}, or create and assign one.

        @type arg:
          L{AutoImporter} or L{BaseIPythonApplication}
        """
        if isinstance(arg, AutoImporter):
            return arg
        app = arg
        subapp = getattr(app, "subapp", None)
        if subapp is not None:
            app = subapp
        try:
            self = app.auto_importer
        except AttributeError:
            pass
        else:
            assert isinstance(self, cls)
            return self
        # Create a new instance and assign to the app.
        self = cls._construct(app)
        app.auto_importer = self
        return self

    @classmethod
    def _construct(cls, app):
        """
        Create a new AutoImporter for C{app}.

        @type app:
          L{IPython.core.application.BaseIPythonApplication}
        """
        self = object.__new__(cls)
        self.app = app
        logger.debug("Constructing %r for app=%r, subapp=%r", self, app,
                     getattr(app, "subapp", None))
        # Functions to call to disable the auto importer.
        self._disablers = []
        # Current enabling state.
        self._state = _EnableState.DISABLED
        # Whether there has been an error implying a bug in pyflyby code or a
        # problem with the import database.
        self._errored = False
        # A reference to the IPython shell object.
        self._ip = None
        # The AST transformer, if any (IPython 1.0+).
        self._ast_transformer = None
        # Dictionary of things we've attempted to autoimport for this cell.
        self._autoimported_this_cell = {}
        return self

    def enable(self, even_if_previously_errored=False):
        """
        Turn on the auto-importer in the current IPython session.
        """
        # Check that we are not enabled/enabling yet.
        if self._state is _EnableState.DISABLED:
            pass
        elif self._state is _EnableState.ENABLED:
            logger.debug("Already enabled")
            return
        elif self._state is _EnableState.ENABLING:
            logger.debug("Already enabling")
            return
        elif self._state is _EnableState.DISABLING:
            logger.debug("Still disabling (run disable() to completion first)")
            return
        else:
            raise AssertionError
        self.reset_state_new_cell()
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
        import IPython
        logger.debug("Enabling auto importer for IPython version %s, pid=%r",
                     IPython.__version__, os.getpid())
        logger.debug("enable(): state %s=>ENABLING", self._state)
        self._errored = False
        self._state = _EnableState.ENABLING
        self._safe_call(self._enable_internal)

    def _continue_enable(self):
        if self._state != _EnableState.ENABLING:
            logger.debug("_enable_internal(): state = %s", self._state)
            return
        logger.debug("Continuing enabling auto importer")
        self._safe_call(self._enable_internal)

    def _enable_internal(self):
        # Main enabling entry point.  This function can get called multiple
        # times, depending on what's been initialized so far.
        app = self.app
        assert app is not None
        if getattr(app, "subapp", None) is not None:
            app = app.subapp
            self.app = app
        logger.debug("app = %r", app)
        ok = True
        ok &= self._enable_ipython_bugfixes()
        ok &= self._enable_initializer_hooks(app)
        ok &= self._enable_kernel_manager_hook(app)
        ok &= self._enable_shell_hooks(app)
        if ok:
            logger.debug("_enable_internal(): success!  state: %s=>ENABLED",
                         self._state)
            self._state = _EnableState.ENABLED
        elif self._pending_initializers:
            logger.debug("_enable_internal(): did what we can for now; "
                         "will enable more after further IPython initialization.  "
                         "state=%s", self._state)
        else:
            logger.debug("_enable_internal(): did what we can, but not "
                         "fully successful.  state: %s=>ENABLED",
                         self._state)
            self._state = _EnableState.ENABLED

    def _enable_initializer_hooks(self, app):
        # Hook initializers.  There are various things we want to hook, and
        # the hooking needs to be done at different times, depending on the
        # IPython version and the "app".  For example, for most versions of
        # IPython, terminal app, many things need to be done after
        # initialize()/init_shell(); on the other hand, in some cases
        # (e.g. IPython console), we need to do stuff *inside* the
        # initialization function.
        # Thus, we take a brute force approach: add hooks to a bunch of
        # places, if they seem to not have run yet, and each time add any
        # hooks that are ready to be added.
        ok = True
        pending = False
        ip = getattr(app, "shell", None)
        if ip is None:
            if hasattr(app, "init_shell"):
                @self._advise(app.init_shell)
                def init_shell_enable_auto_importer():
                    __original__()
                    logger.debug("init_shell() completed")
                    ip = app.shell
                    if ip is None:
                        logger.debug("Aborting enabling AutoImporter: "
                                     "even after init_shell(), "
                                     "still no shell in app=%r", app)
                        return
                    self._continue_enable()
            elif not hasattr(app, "shell") and hasattr(app, "kernel_manager"):
                logger.debug("No shell applicable; ok because using kernel manager")
                pass
            else:
                logger.debug("App shell missing and no init_shell() to advise")
                ok = False
            if hasattr(app, "initialize_subcommand"):
                # Hook the subapp, if any.  This requires some cleverness:
                # 'ipython console' requires us to do some stuff *before*
                # initialize() is called on the new app, while 'ipython
                # notebook' requires us to do stuff *after* initialize() is
                # called.
                @self._advise(app.initialize_subcommand)
                def init_subcmd_enable_auto_importer(*args, **kwargs):
                    logger.debug("initialize_subcommand()")
                    from IPython.core.application import Application
                    @advise((Application, "instance"))
                    def app_instance_enable_auto_importer(cls, *args, **kwargs):
                        logger.debug("%s.instance()", cls.__name__)
                        app = __original__(cls, *args, **kwargs)
                        if app != self.app:
                            self.app = app
                            self._continue_enable()
                        return app
                    try:
                        __original__(*args, **kwargs)
                    finally:
                        app_instance_enable_auto_importer.unadvise()
                    self._continue_enable()
            pending = True
        if (hasattr(ip, "post_config_initialization") and
            not hasattr(ip, "rl_next_input")):
            # IPython 0.10 might not be ready to hook yet because we're called
            # from the config phase, and certain stuff (like Completer) is set
            # up in post-config.  Re-run after post_config_initialization.
            # Kludge: post_config_initialization() sets ip.rl_next_input=None,
            # so detect whether it's been run by checking for that attribute.
            @self._advise(ip.post_config_initialization)
            def post_config_enable_auto_importer():
                __original__()
                logger.debug("post_config_initialization() completed")
                if not hasattr(ip, "rl_next_input"):
                    # Post-config initialization failed?
                    return
                self._continue_enable()
            pending = True
        self._pending_initializers = pending
        return ok

    def _enable_kernel_manager_hook(self, app):
        # For IPython notebook, by the time we get here, there's generally a
        # kernel_manager already assigned, but kernel_manager.start_kernel()
        # hasn't been called yet.  Hook app.kernel_manager.start_kernel().
        kernel_manager = getattr(app, "kernel_manager", None)
        ok = True
        if kernel_manager is not None:
            ok &= self._enable_start_kernel_hook(kernel_manager)
        # For IPython console, a single function constructs the kernel_manager
        # and then immediately calls kernel_manager.start_kernel().  The
        # easiest way to intercept start_kernel() is by installing a hook
        # after the kernel_manager is constructed.
        if getattr(app, "kernel_manager_class", None) is not None:
            @self._advise((app, "kernel_manager_class"))
            def kernel_manager_class_with_autoimport(*args, **kwargs):
                kernel_manager = __original__(*args, **kwargs)
                self._enable_start_kernel_hook(kernel_manager)
                return kernel_manager
        # It's OK if no kernel_manager nor kernel_manager_class; this is the
        # typical case, when using regular IPython terminal console (not
        # IPython notebook/console).
        return True

    def _enable_start_kernel_hook(self, kernel_manager):
        try:
            # Tested with IPython 1.0, 1.2, 2.0, 2.1, 2.2, 2.3
            from IPython.kernel.manager import KernelManager
        except ImportError:
            pass
        else:
            @self._advise(kernel_manager.start_kernel)
            def start_kernel_with_autoimport(*args, **kwargs):
                logger.debug("start_kernel()")
                # Advise format_kernel_cmd(), which is the function that
                # computes the command line for a subprocess to run a new
                # kernel.  Note that we advise the method on the class, rather
                # than this instance of kernel_manager, because start_kernel()
                # actually creates a *new* KernelInstance for this.
                @advise(KernelManager.format_kernel_cmd)
                def format_kernel_cmd_with_autoimport(*args, **kwargs):
                    result = __original__(*args, **kwargs)
                    try:
                        carg = result.index("-c")
                    except ValueError:
                        logger.debug("couldn't parse output of format_kernel_cmd(): %r", result)
                        return result
                    cmd = result[carg+1]
                    expected_cmd = 'from IPython.kernel.zmq.kernelapp import main; main()'
                    if cmd != expected_cmd:
                        logger.debug("unexpected command, not modifying it: %r", cmd)
                        return result
                    new_cmd = (
                        'from pyflyby._interactive import start_ipython_kernel_with_autoimporter; '
                        'start_ipython_kernel_with_autoimporter()')
                    result[carg+1] = new_cmd
                    return result
                try:
                    return __original__(*args, **kwargs)
                finally:
                    format_kernel_cmd_with_autoimport.unadvise()
            return True
        # Tested with IPython 0.12, 0.13
        try:
            import IPython.zmq.ipkernel
        except ImportError:
            pass
        else:
            @self._advise(kernel_manager.start_kernel)
            def start_kernel_with_autoimport013(*args, **kwargs):
                logger.debug("start_kernel()")
                @advise((IPython.zmq.ipkernel, 'base_launch_kernel'))
                def base_launch_kernel_with_autoimport(cmd, *args, **kwargs):
                    logger.debug("base_launch_kernel()")
                    expected_cmd = 'from IPython.zmq.ipkernel import main; main()'
                    if cmd != expected_cmd:
                        logger.debug("unexpected command, not modifying it: %r", cmd)
                    else:
                        cmd = (
                            'from pyflyby._interactive import start_ipython_kernel_with_autoimporter; '
                            'start_ipython_kernel_with_autoimporter()')
                    return __original__(cmd, *args, **kwargs)
                try:
                    return __original__(*args, **kwargs)
                finally:
                    base_launch_kernel_with_autoimport.unadvise()
            return True
        logger.debug("Couldn't enable start_kernel hook")
        return False

    def _enable_shell_hooks(self, app):
        """
        Enable hooks to run auto_import before code execution.
        """
        # Check again in case this was registered delayed
        if self._state != _EnableState.ENABLING:
            return False
        try:
            ip = app.shell
        except AttributeError:
            logger.debug("_enable_shell_hooks(): no shell at all")
            return True
        if ip is None:
            logger.debug("_enable_shell_hooks(): no shell yet")
            return False
        logger.debug("Enabling IPython shell hooks, shell=%r", ip)
        self._ip = ip
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
        ok = True
        ok &= self._enable_reset_hook(ip)
        ok &= self._enable_ofind_hook(ip)
        ok &= self._enable_ast_hook(ip)
        ok &= self._enable_time_hook(ip)
        ok &= self._enable_timeit_hook(ip)
        ok &= self._enable_prun_hook(ip)
        ok &= self._enable_completion_hook(ip)
        ok &= self._enable_run_hook(ip)
        ok &= self._enable_ipython_shell_bugfixes(ip)
        return ok

    def _enable_reset_hook(self, ip):
        # Register a hook that resets autoimporter state per input cell.
        # The only per-input-cell state we currently have is the recording of
        # which autoimports we've attempted but failed.  We keep track of this
        # to avoid multiple error messages for a single import, in case of
        # overlapping hooks.
        # Note: Some of the below approaches (both registering an
        # input_transformer_manager hook or advising reset()) cause the reset
        # function to get called twice per cell.  This seems like an
        # unintentional repeated call in IPython itself.  This is harmless for
        # us, since doing an extra reset shouldn't hurt.
        if hasattr(ip, "input_transformer_manager"):
            # Tested with IPython 1.0, 1.2, 2.0, 2.1, 2.2, 2.3.
            class ResetAutoImporterState(object):
                def push(self_, line):
                    return line
                def reset(self_):
                    logger.debug("ResetAutoImporterState.reset()")
                    self.reset_state_new_cell()
            t = ResetAutoImporterState()
            transforms = ip.input_transformer_manager.python_line_transforms
            transforms.append(t)
            def unregister_input_transformer():
                try:
                    transforms.remove(t)
                except ValueError:
                    logger.info(
                        "Couldn't remove python_line_transformer hook")
            self._disablers.append(unregister_input_transformer)
            return True
        elif hasattr(ip, "input_splitter"):
            # Tested with IPython 0.13.  Also works with later versions, but
            # for those versions, we can use a real hook instead of advising.
            @self._advise(ip.input_splitter.reset)
            def reset_input_splitter_and_autoimporter_state():
                logger.debug("reset_input_splitter_and_autoimporter_state()")
                self.reset_state_new_cell()
                return __original__()
            return True
        elif hasattr(ip, "resetbuffer"):
            # Tested with IPython 0.10.
            @self._advise(ip.resetbuffer)
            def resetbuffer_and_autoimporter_state():
                logger.debug("resetbuffer_and_autoimporter_state")
                self.reset_state_new_cell()
                return __original__()
            return True
        else:
            logger.debug("Couldn't enable reset hook")
            return False

    def _enable_ofind_hook(self, ip):
        """
        Enable a hook of _ofind(), which is used for pinfo, autocall, etc.
        """
        # Advise _ofind.
        if hasattr(ip, "_ofind"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @self._advise(ip._ofind)
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
            return True
        else:
            logger.debug("Couldn't enable ofind hook")
            return False

    def _enable_ast_hook(self, ip):
        """
        Enable a hook somewhere in the source => parsed AST => compiled code
        pipeline.
        """
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
            return True
        elif hasattr(ip, "run_ast_nodes"):
            # Second choice: advise the run_ast_nodes() function.  Tested with
            # IPython 0.11, 0.12, 0.13.  This is the most robust way available
            # for those versions.
            # (ip.compile.ast_parse also works in IPython 0.12-0.13; no major
            # flaw, but might as well use the same mechanism that works in
            # 0.11.)
            @self._advise(ip.run_ast_nodes)
            def run_ast_nodes_with_autoimport(nodelist, *args, **kwargs):
                logger.debug("run_ast_nodes")
                ast_node = ast.Module(nodelist)
                self.auto_import(ast_node)
                return __original__(nodelist, *args, **kwargs)
            return True
        elif hasattr(ip, 'compile'):
            # Third choice: Advise ip.compile.
            # Tested with IPython 0.10.
            # We don't hook prefilter because that gets called once per line,
            # not per multiline code.
            # We don't hook runsource because that gets called incrementally
            # with partial multiline source until the source is complete.
            @self._advise((ip, "compile"))
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
            return True
        else:
            logger.debug("Couldn't enable parse hook")
            return False

    def _enable_time_hook(self, ip):
        """
        Enable a hook so that %time will autoimport.
        """
        # For IPython 1.0+, the ast_transformer takes care of it.
        if self._ast_transformer:
            return True
        # Otherwise, we advise %time to temporarily override the compile()
        # builtin within it.
        if hasattr(ip, 'magics_manager'):
            # Tested with IPython 0.13.  (IPython 1.0+ also has
            # magics_manager, but for those versions, ast_transformer takes
            # care of %time.)
            line_magics = ip.magics_manager.magics['line']
            @self._advise((line_magics, 'time'))
            def time_with_autoimport(*args, **kwargs):
                logger.debug("time_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            return True
        elif hasattr(ip, 'magic_time'):
            # Tested with IPython 0.10, 0.11, 0.12
            @self._advise(ip.magic_time)
            def magic_time_with_autoimport(*args, **kwargs):
                logger.debug("time_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            return True
        else:
            logger.debug("Couldn't enable time hook")
            return False

    def _enable_timeit_hook(self, ip):
        """
        Enable a hook so that %timeit will autoimport.
        """
        # For IPython 1.0+, the ast_transformer takes care of it.
        if self._ast_transformer:
            return True
        # Otherwise, we advise %timeit to temporarily override the compile()
        # builtin within it.
        if hasattr(ip, 'magics_manager'):
            # Tested with IPython 0.13.  (IPython 1.0+ also has
            # magics_manager, but for those versions, ast_transformer takes
            # care of %timeit.)
            line_magics = ip.magics_manager.magics['line']
            @self._advise((line_magics, 'timeit'))
            def timeit_with_autoimport(*args, **kwargs):
                logger.debug("timeit_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            return True
        elif hasattr(ip, 'magic_timeit'):
            # Tested with IPython 0.10, 0.11, 0.12
            @self._advise(ip.magic_timeit)
            def magic_timeit_with_autoimport(*args, **kwargs):
                logger.debug("timeit_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, compile=self.compile_with_autoimport)
                return wrapped(*args, **kwargs)
            return True
        else:
            logger.debug("Couldn't enable timeit hook")
            return False

    def _enable_prun_hook(self, ip):
        """
        Enable a hook so that %prun will autoimport.
        """
        if hasattr(ip, 'magics_manager'):
            # Tested with IPython 1.0, 1.1, 1.2, 2.0, 2.1, 2.2, 2.3.
            line_magics = ip.magics_manager.magics['line']
            execmgr = line_magics['prun'].im_self
            if hasattr(execmgr, "_run_with_profiler"):
                @self._advise(execmgr._run_with_profiler)
                def run_with_profiler_with_autoimport(code, opts, namespace):
                    logger.debug("run_with_profiler_with_autoimport()")
                    self.auto_import(code, [namespace])
                    return __original__(code, opts, namespace)
                return True
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
                @self._advise((line_magics, 'prun'))
                def prun_with_autoimport(*args, **kwargs):
                    logger.debug("prun_with_autoimport()")
                    wrapped = FunctionWithGlobals(
                        __original__, profile=ProfileFactory_with_autoimport())
                    return wrapped(*args, **kwargs)
                return True
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
            @self._advise(ip.magic_prun)
            def magic_prun_with_autoimport(*args, **kwargs):
                logger.debug("magic_prun_with_autoimport()")
                wrapped = FunctionWithGlobals(
                    __original__, profile=ProfileFactory_with_autoimport())
                return wrapped(*args, **kwargs)
            return True
        else:
            logger.debug("Couldn't enable prun hook")
            return False

    def _enable_completion_hook(self, ip):
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
        completer = getattr(ip, "Completer", None)
        if hasattr(completer, "global_matches"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @self._advise(ip.Completer.global_matches)
            def global_matches_with_autoimport(fullname):
                return self.complete_symbol(fullname, on_error=__original__)
            @self._advise(ip.Completer.attr_matches)
            def attr_matches_with_autoimport(fullname):
                return self.complete_symbol(fullname, on_error=__original__)
            return True
        elif hasattr(completer, "complete_request"):
            # This is a ZMQCompleter, so nothing to do.
            return True
        else:
            logger.debug("Couldn't enable completion hook")
            return False

    def _enable_run_hook(self, ip):
        """
        Enable a hook so that %run will autoimport.
        """
        if hasattr(ip, "safe_execfile"):
            # Tested with IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.3
            @self._advise(ip.safe_execfile)
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
            return True
        else:
            logger.debug("Couldn't enable execfile hook")
            return False

    def _enable_ipython_shell_bugfixes(self, ip):
        """
        Enable some advice that's actually just fixing bugs in IPython.
        """
        # IPython 2.x on Python 2.x has a bug where 'run -n' doesn't work
        # because it uses Unicode for the module name.  This is a bug in
        # IPython itself ("run -n" is plain broken for ipython-2.x on
        # python-2.x); we patch it here.
        if (sys.version_info < (3,) and
            hasattr(ip, "new_main_mod") and
            inspect.getargspec(ip.new_main_mod).args == ["self","filename","modname"]):
            @self._advise(ip.new_main_mod)
            def new_main_mod_fix_str(filename, modname):
                if type(modname) is unicode:
                    modname = str(modname)
                return __original__(filename, modname)
        return True

    def _enable_ipython_bugfixes(self):
        """
        Enable some advice that's actually just fixing bugs in IPython.
        """
        try:
            from IPython.config.application import LevelFormatter
        except ImportError:
            pass
        else:
            if (not issubclass(LevelFormatter, object) and
                "super" in LevelFormatter.format.im_func.func_code.co_names and
                "logging" not in LevelFormatter.format.im_func.func_code.co_names):
                # In IPython 1.0, LevelFormatter uses super(), which assumes
                # that logging.Formatter is a subclass of object.  However,
                # this is only true in Python 2.7+, not in Python 2.6.  So
                # Python 2.6 + IPython 1.0 causes problems.  IPython 1.2
                # already includes this fix.
                from logging import Formatter
                @self._advise(LevelFormatter.format)
                def format_patched(self, record):
                    if record.levelno >= self.highlevel_limit:
                        record.highlevel = self.highlevel_format % record.__dict__
                    else:
                        record.highlevel = ""
                    return Formatter.format(self, record)
        return True

    def disable(self):
        """
        Turn off auto-importer in the current IPython session.
        """
        if self._state is _EnableState.DISABLED:
            logger.debug("disable(): already disabled")
            return
        logger.debug("disable(): state: %s=>DISABLING", self._state)
        self._state = _EnableState.DISABLING
        while self._disablers:
            f = self._disablers.pop(-1)
            try:
                f()
            except Exception as e:
                self._errored = True
                logger.error("Error while disabling: %s: %s", type(e).__name__, e)
                if logger.debug_enabled:
                    raise
                else:
                    logger.info(
                        "Set the env var PYFLYBY_LOG_LEVEL=DEBUG to debug.")
        logger.debug("disable(): state: %s=>DISABLED", self._state)
        self._state = _EnableState.DISABLED

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

    def reset_state_new_cell(self):
        # Reset the state for a new cell.
        if logger.debug_enabled:
            autoimported = self._autoimported_this_cell
            logger.debug("reset_state_new_cell(): previously autoimported: "
                         "succeeded=%s, failed=%s",
                         sorted([k for k,v in autoimported.items() if v]),
                         sorted([k for k,v in autoimported.items() if not v]))
        self._autoimported_this_cell = {}

    def auto_import(self, arg, namespaces=None,
                    raise_on_error='if_debug', on_error=None):
        if namespaces is None:
            namespaces = get_global_namespaces(self._ip)
        return self._safe_call(
            auto_import, arg, namespaces,
            autoimported=self._autoimported_this_cell,
            raise_on_error=raise_on_error, on_error=on_error)

    def complete_symbol(self, fullname,
                        raise_on_error='if_debug', on_error=None):
        with InterceptPrintsDuringPromptCtx(self._ip):
            namespaces = get_global_namespaces(self._ip)
            if on_error is not None:
                def on_error1(fullname, namespaces, autoimported, ip):
                    return on_error(fullname)
            else:
                on_error1 = None
            return self._safe_call(
                complete_symbol, fullname, namespaces,
                autoimported=self._autoimported_this_cell,
                ip=self._ip,
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

    def _advise(self, joinpoint):
        def advisor(f):
            aspect = Aspect(joinpoint)
            if aspect.advise(f, once=True):
                self._disablers.append(aspect.unadvise)
        return advisor



def enable_auto_importer(if_no_ipython='raise'):
    """
    Turn on the auto-importer in the current IPython application.

    @param if_no_ipython:
      If we are not inside IPython and if_no_ipython=='ignore', then silently
      do nothing.
      If we are not inside IPython and if_no_ipython=='raise', then raise
      NoIPythonAppError.
    """
    try:
        app = _get_ipython_app()
    except NoIPythonAppError:
        if if_no_ipython=='ignore':
            return
        else:
            raise
    auto_importer = AutoImporter(app)
    auto_importer.enable()


def disable_auto_importer():
    """
    Turn off the auto-importer in the current IPython application.
    """
    try:
        app = _get_ipython_app()
    except NoIPythonAppError:
        return
    auto_importer = AutoImporter(app)
    auto_importer.disable()
