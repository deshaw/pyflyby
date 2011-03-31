from __future__             import absolute_import, division, with_statement
import ast
import operator
import optparse
import os
import re
import sys
from collections            import defaultdict, namedtuple
from pyflyby.file       import Filename, modify_file, read_file
from pyflyby.format     import FormatParams, pyfill
from pyflyby.importdb   import global_importdb
from pyflyby.importstmt import (ImportFormatParams, Imports,
                                    NoSuchImportError)
from pyflyby.parse      import PythonBlock, PythonFileLines, PythonStatement
from pyflyby.s2s        import (fix_unused_and_missing_imports,
                                    reformat_import_statements)
from pyflyby.util       import (Inf, cached_attribute,
                                    longest_common_prefix, stable_unique)
from itertools              import groupby
