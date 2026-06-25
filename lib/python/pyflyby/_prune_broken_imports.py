"""
prune-broken-imports *.py
prune-broken-imports < foo.py

Removes broken imports.

Note: This actually executes imports.

If filenames are given on the command line, rewrites them.  Otherwise, if
stdin is not a tty, read from stdin and write to stdout.

Only top-level import statements are touched.

"""
# pyflyby/_prune_broken_imports.py
# Copyright (C) 2012, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


from   pyflyby._cmdline         import parse_args, process_actions
from   pyflyby._imports2s       import remove_broken_imports


def main():
    # ``parse_args`` derives the --help/usage banner from ``__main__.__doc__``
    # (see ``pyflyby._cmdline.maindoc``).  When invoked through the console
    # script entry point the ``__main__`` module is the generated wrapper and
    # has no docstring, so fall back to this module's docstring.
    import __main__
    if not (__main__.__doc__ or '').strip():
        __main__.__doc__ = __doc__

    options, args = parse_args(modify_action_params=True)
    def modify(x):
        return remove_broken_imports(x, params=options.params)
    process_actions(args, options.actions, modify)


if __name__ == '__main__':
    main()
