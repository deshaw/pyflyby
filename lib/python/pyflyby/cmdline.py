
from __future__ import absolute_import, division, with_statement

import optparse
import os
import sys

from pyflyby.file       import Filename, STDIO_PIPE
from pyflyby.importstmt import ImportFormatParams

def parse_args():
    parser = optparse.OptionParser()
    parser.add_option('--align-imports', type='int', default=1,
                      help='''
                          Whether and how to align the 'import' keyword in
                          'from modulename import aliases...'.  If 0, then
                          don't align.  If 1 (default), then align within each
                          block of imports.  If an integer > 1, then align at
                          that column, wrapping with a backslash if
                          necessary.''')
    parser.add_option('--from-spaces', type='int',
                      help='''
                          The number of spaces after the 'from' keyword.
                          (Must be at least 1.)''')
    options, args = parser.parse_args()
    if options.align_imports == 1:
        align_imports = True
    elif options.align_imports == 0:
        align_imports = False
    else:
        align_imports = options.align_imports
    options.params = ImportFormatParams(
        align_imports =align_imports,
        from_spaces   =options.from_spaces)
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
