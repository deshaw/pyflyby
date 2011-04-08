
from __future__ import absolute_import, division, with_statement

import optparse
import os
import sys
from   textwrap                 import dedent

from   pyflyby.file             import Filename, STDIO_PIPE
from   pyflyby.importstmt       import ImportFormatParams

def parse_args(import_format_params=False):
    parser = optparse.OptionParser()
    if import_format_params:
        parser.add_option('--align-imports', type='int', default=1,
                          help=dedent('''
                              Whether and how to align the 'import' keyword in
                              'from modulename import aliases...'.  If 0, then
                              don't align.  If 1 (default), then align within
                              each block of imports.  If an integer > 1, then
                              align at that column, wrapping with a backslash
                              if necessary.'''))
        parser.add_option('--from-spaces', type='int', default=1,
                          help=dedent('''
                              The number of spaces after the 'from' keyword.
                              (Must be at least 1.)'''))
        parser.add_option('--separate-from-imports', action='store_true',
                          default=True,
                          help=dedent('''
                              (Default) Separate 'from ... import ...'
                              statements from 'import ...' statements.'''))
        parser.add_option('--no-separate-from-imports', action='store_false',
                          dest='separate_from_imports',
                          help=dedent('''
                              Don't separate 'from ... import ...' statements
                              from 'import ...' statements.'''))
        parser.add_option('--width', type='int', default=79,
                          help=dedent('Maximum line length (default: 79).'))
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
