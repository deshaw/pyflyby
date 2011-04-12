
from __future__ import absolute_import, division, with_statement

import optparse
import os
import sys
from   textwrap                 import dedent

from   pyflyby.file             import Filename, STDIO_PIPE
from   pyflyby.importstmt       import ImportFormatParams
from   pyflyby.log              import logger

def hfmt(s):
    return dedent(s).strip()

def parse_args(addopts=None, import_format_params=False):
    parser = optparse.OptionParser()

    def log_level_callbacker(level):
        def callback(option, opt_str, value, parser):
            logger.set_level(level)
        return callback

    parser.add_option("--debug", "--verbose", action="callback",
                      callback=log_level_callbacker("debug"))

    parser.add_option("--quiet", action="callback",
                      callback=log_level_callbacker("error"))

    if import_format_params:
        group = optparse.OptionGroup(parser, "Pretty-printing options")
        group.add_option('--align-imports', '--align', type='int', default=0,
                         help=hfmt('''
                             Whether and how to align the 'import' keyword in
                             'from modulename import aliases...'.  If 0
                             (default), then don't align.  If 1, then align
                             within each block of imports.  If an integer > 1,
                             then align at that column, wrapping with a
                             backslash if necessary.'''))
        group.add_option('--from-spaces', type='int', default=1,
                         help=hfmt('''
                             The number of spaces after the 'from' keyword.
                             (Must be at least 1.)'''))
        group.add_option('--separate-from-imports', action='store_true',
                         default=True,
                         help=hfmt('''
                             (Default) Separate 'from ... import ...'
                             statements from 'import ...' statements.'''))
        group.add_option('--no-separate-from-imports', action='store_false',
                         dest='separate_from_imports',
                         help=hfmt('''
                            Don't separate 'from ... import ...' statements
                            from 'import ...' statements.'''))
        group.add_option('--align-future', action='store_true',
                         default=False,
                         help=hfmt('''
                             Align the 'from __future__ import ...' statement
                             like others.'''))
        group.add_option('--width', type='int', default=79,
                         help=hfmt('''
                             Maximum line length (default: 79).'''))
        def uniform_callback(option, opt_str, value, group):
            group.values.separate_from_imports = False
            group.values.from_spaces           = 3
            group.values.align_imports         = 32
        group.add_option('--uniform', '-u', action="callback",
                         callback=uniform_callback,
                         help=hfmt('''
                             Shortcut for --no-separate-from-imports
                             --from-spaces=3 --align-imports=32.'''))
        parser.add_option_group(group)
    if addopts is not None:
        addopts(parser)
    options, args = parser.parse_args()
    if import_format_params:
        if options.align_imports == 1:
            align_imports = True
        elif options.align_imports == 0:
            align_imports = False
        else:
            align_imports = options.align_imports
        options.params = ImportFormatParams(
            align_imports         =align_imports,
            from_spaces           =options.from_spaces,
            separate_from_imports =options.separate_from_imports,
            max_line_length       =options.width,
            align_future          = options.align_future
            )
    return options, args

def filename_args(args):
    if args:
        filenames = [Filename(arg) for arg in args]
        for filename in filenames:
            if not filename.isfile:
                raise Exception("%s doesn't exist as a file" % (filename,))
        return filenames
    elif not os.isatty(0):
        return [STDIO_PIPE]
    else:
        syntax()

def syntax():
    import __main__
    print >>sys.stderr, __main__.__doc__
    raise SystemExit(1)
