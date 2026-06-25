"""
Usage: find-import names...

Prints how to import given name(s).
"""
# pyflyby/_find_import.py
# Copyright (C) 2011, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


from   pyflyby._cmdline         import parse_args, syntax
from   pyflyby._importdb        import ImportDB
from   pyflyby._log             import logger


def main():
    # ``parse_args``/``syntax`` derive the --help/usage banner from
    # ``__main__.__doc__`` (see ``pyflyby._cmdline.maindoc``).  When invoked
    # through the console script entry point the ``__main__`` module is the
    # generated wrapper and has no docstring, so fall back to this module's.
    import __main__
    if not (__main__.__doc__ or '').strip():
        __main__.__doc__ = __doc__

    options, args = parse_args()
    if not args:
        syntax()
    db = ImportDB.get_default(".")
    known = db.known_imports.by_import_as
    errors = 0
    for arg in args:
        try:
            imports = known[arg]
        except KeyError:
            errors += 1
            logger.error("Can't find import for %r", arg)
        else:
            for imp in imports:
                print(imp.pretty_print(params=options.params), end=' ')
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
