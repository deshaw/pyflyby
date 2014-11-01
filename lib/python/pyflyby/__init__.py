# pyflyby/__init__.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import absolute_import, division, with_statement

from   pyflyby._autoimp         import auto_eval, find_missing_imports
from   pyflyby._file            import Filename
from   pyflyby._importdb        import ImportDB
from   pyflyby._imports2s       import (canonicalize_imports,
                                        reformat_import_statements,
                                        remove_broken_imports,
                                        replace_star_imports,
                                        transform_imports)
from   pyflyby._importstmt      import (Import, ImportStatement,
                                        NonImportStatementError)
from   pyflyby._interactive     import install_auto_importer
from   pyflyby._log             import logger
from   pyflyby._parse           import PythonBlock, PythonStatement
from   pyflyby._version         import __version__


# Promote the function & classes that we've chosen to expose publicly to be
# known as pyflyby.Foo instead of pyflyby._module.Foo.
for x in globals().values():
    if getattr(x, "__module__", "").startswith("pyflyby."):
        x.__module__ = "pyflyby"
del x


# Discourage "from pyflyby import *".
# Use the tidy-imports/autoimporter instead!
__all__ = []
