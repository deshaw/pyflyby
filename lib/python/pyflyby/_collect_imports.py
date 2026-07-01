"""
collect-imports *.py
collect-imports < foo.py

Collect all imports from named files or stdin, and combine them into a single
block of import statements.  Print the result to stdout.

"""
# pyflyby/_collect_imports.py
# Copyright (C) 2011, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


import re
import sys

from   pyflyby._cmdline         import filename_args, hfmt, parse_args
from   pyflyby._importclns      import ImportSet
from   pyflyby._importdb        import ImportDB


def main():
    # ``parse_args`` derives the --help/usage banner from ``__main__.__doc__``
    # (see ``pyflyby._cmdline.maindoc``).  When invoked through the console
    # script entry point the ``__main__`` module is the generated wrapper and
    # has no docstring, so fall back to this module's docstring.
    import __main__
    if not (__main__.__doc__ or '').strip():
        __main__.__doc__ = __doc__

    def addopts(parser):
        parser.add_option("--ignore-known", default=False, action='store_true',
                          help=hfmt('''
                                Don't list imports already in the
                                known-imports database.'''))
        parser.add_option("--no-ignore-known", dest="ignore_known",
                          action='store_false',
                          help=hfmt('''
                                (Default) List all imports, including those
                                already in the known-imports database.'''))
        parser.add_option("--include",
                          default=[], action="append",
                          help=hfmt('''
                                Include only imports under the given package.'''))
    options, args = parse_args(addopts)
    filenames = filename_args(args)
    importset = ImportSet(filenames, ignore_nonimports=True)
    if options.include:
        regexps = [
            re.escape(prefix) if prefix.endswith(".") else
            re.escape(prefix) + "([.]|$)"
            for prefix in options.include
        ]
        regexp = re.compile("|".join(regexps))
        match = lambda imp: regexp.match(imp.fullname)
        importset = ImportSet([imp for imp in importset if match(imp)])
    if options.ignore_known:
        db = ImportDB.get_default(".")
        importset = importset.without_imports(db.known_imports)
    sys.stdout.write(importset.pretty_print(
            allow_conflicts=True, params=options.params))


if __name__ == '__main__':
    main()
