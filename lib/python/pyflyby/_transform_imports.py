"""
transform-imports --transform aa.bb=xx.yy *.py
transform-imports --transform aa.bb=xx.yy < foo.py

Transforms::
  from aa.bb.cc import dd, ee
  from aa import bb
to::
  from xx.yy.cc import dd, ee
  from xx import yy as bb

If filenames are given on the command line, rewrites them.  Otherwise, if
stdin is not a tty, read from stdin and write to stdout.

"""

# pyflyby/_transform_imports.py
# Copyright (C) 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT


from   pyflyby._cmdline         import hfmt, parse_args, process_actions
from   pyflyby._imports2s       import transform_imports


def main():
    # ``parse_args`` derives the --help/usage banner from ``__main__.__doc__``
    # (see ``pyflyby._cmdline.maindoc``).  When invoked through the console
    # script entry point the ``__main__`` module is the generated wrapper and
    # has no docstring, so fall back to this module's docstring.
    import __main__
    if not (__main__.__doc__ or '').strip():
        __main__.__doc__ = __doc__

    transformations = {}
    def addopts(parser):
        def callback(option, opt_str, value, group):
            k, v = value.split("=", 1)
            transformations[k] = v
        parser.add_option("--transform", action='callback',
                          type="string", callback=callback,
                          metavar="OLD=NEW",
                          help=hfmt('''
                                Replace OLD with NEW in imports.
                                May be specified multiple times.'''))
        parser.add_option('--transform-strings', dest='transform_strings',
                          default=False, action='store_true',
                          help=hfmt('''
                                When using --transform, also replace matches
                                inside string literals (including docstrings
                                and f-string text).  Off by default.'''))
    options, args = parse_args(
        addopts, modify_action_params=True)
    def modify(x):
        return transform_imports(x, transformations, params=options.params,
                                 transform_strings=options.transform_strings)
    process_actions(args, options.actions, modify)


if __name__ == '__main__':
    main()
