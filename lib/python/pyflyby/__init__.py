# pyflyby/__init__.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



from   pyflyby._autoimp         import (auto_eval, auto_import,
                                        find_missing_imports)
from   pyflyby._dbg             import (add_debug_functions_to_builtins,
                                        attach_debugger, debug_on_exception,
                                        debug_statement, debugger,
                                        enable_exception_handler_debugger,
                                        enable_faulthandler,
                                        enable_signal_handler_debugger,
                                        print_traceback, remote_print_stack)
from   pyflyby._dynimp          import add_import
from   pyflyby._file            import Filename
from   pyflyby._flags           import CompilerFlags
from   pyflyby._importdb        import ImportDB
from   pyflyby._imports2s       import (canonicalize_imports,
                                        reformat_import_statements,
                                        remove_broken_imports,
                                        replace_star_imports,
                                        transform_imports)
from   pyflyby._importstmt      import (Import, ImportStatement,
                                        NonImportStatementError)
from   pyflyby._interactive     import (disable_auto_importer,
                                        enable_auto_importer,
                                        install_in_ipython_config_file,
                                        load_ipython_extension,
                                        unload_ipython_extension)
from   pyflyby._livepatch       import livepatch, xreload
from   pyflyby._log             import logger
from   pyflyby._modules         import rebuild_import_cache
from   pyflyby._parse           import PythonBlock, PythonStatement
from   pyflyby._saveframe       import saveframe
from   pyflyby._saveframe_reader \
                                import SaveframeReader
from   pyflyby._version         import __version__

# Deprecated:
from   pyflyby._dbg             import (breakpoint, debug_exception,
                                        debug_statement,
                                        enable_exception_handler,
                                        enable_signal_handler_breakpoint,
                                        waitpoint)

from   typing                   import Sequence


# Promote the function & classes that we've chosen to expose publicly to be
# known as pyflyby.Foo instead of pyflyby._module.Foo.
for x in list(globals().values()):
    if getattr(x, "__module__", "").startswith("pyflyby."):
        x.__module__ = "pyflyby"
del x


# Discourage "from pyflyby import *".
# Use the tidy-imports/autoimporter instead!
__all__:Sequence[str] = []
