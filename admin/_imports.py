from __future__ import absolute_import, division, with_statement
import __builtin__
import ast
from   collections              import defaultdict, namedtuple
from   epydoc.apidoc            import (ClassDoc, ModuleDoc, PropertyDoc,
                                        RoutineDoc, UNKNOWN, VariableDoc)
from   epydoc.docbuilder        import build_doc_index
from   epydoc.markup.plaintext  import ParsedPlaintextDocstring
from   itertools                import groupby
import logging
import operator
import optparse
import os
from   pyflyby.cmdline          import filename_args, parse_args, syntax
from   pyflyby.docxref          import find_bad_doc_cross_references
from   pyflyby.file             import (FileContents, FileLines, Filename,
                                        STDIO_PIPE, modify_file, read_file)
from   pyflyby.format           import FormatParams, pyfill
from   pyflyby.importdb         import (global_known_imports,
                                        global_mandatory_imports)
from   pyflyby.imports2s        import (fix_unused_and_missing_imports,
                                        reformat_import_statements)
from   pyflyby.importstmt       import (ImportFormatParams, Imports,
                                        NoSuchImportError)
from   pyflyby.log              import logger
from   pyflyby.modules          import Module, SymbolName
from   pyflyby.parse            import (PythonBlock, PythonFileLines,
                                        PythonStatement)
from   pyflyby.util             import (Inf, cached_attribute,
                                        longest_common_prefix, memoize,
                                        prefixes, stable_unique, union_dicts)
import re
import sys
from   textwrap                 import dedent
import types
