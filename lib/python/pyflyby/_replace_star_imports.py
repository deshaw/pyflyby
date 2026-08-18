"""
replace-star-imports *.py
replace-star-imports < foo.py

Replaces::
  from foo.bar import *
with::
  from foo.bar import (f1, f2, ...)

Note: This actually executes imports.

If filenames are given on the command line, rewrites them.  Otherwise, if
stdin is not a tty, read from stdin and write to stdout.

Only top-level import statements are touched.

"""
# pyflyby/_replace_star_imports.py
# Copyright (C) 2012, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


from   pyflyby._cmdline         import hfmt, parse_args, process_actions
from   pyflyby._file            import FileText
from   pyflyby._imports2s       import replace_star_imports
from   pyflyby._parse           import PythonBlock


def main():
    # ``parse_args`` derives the --help/usage banner from ``__main__.__doc__``
    # (see ``pyflyby._cmdline.maindoc``).  When invoked through the console
    # script entry point the ``__main__`` module is the generated wrapper and
    # has no docstring, so fall back to this module's docstring.
    import __main__
    if not (__main__.__doc__ or '').strip():
        __main__.__doc__ = __doc__

    def addopts(parser):
        parser.add_option('--exec-star-imports',
                          default=False, action='store_true',
                          help=hfmt('''
                              Import modules to find out what a star import
                              supplies, rather than only parsing their source
                              (which misses a run-time __all__, e.g. numpy's).
                              This executes the module.'''))
        parser.add_option('--no-exec-star-imports',
                          dest='exec_star_imports', action='store_false',
                          help=hfmt('''
                              (Default) Only parse module source
                              statically.'''))

    options, args = parse_args(addopts, modify_action_params=True)
    def modify(x:FileText,/) -> PythonBlock:
        return replace_star_imports(
            PythonBlock(x), params=options.params,
            exec_star_imports=options.exec_star_imports)
    process_actions(args, options.actions, modify)


if __name__ == '__main__':
    main()
