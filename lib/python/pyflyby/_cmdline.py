# pyflyby/_cmdline.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT



from   builtins                 import input
import optparse
import os
from   pathlib                  import Path
import signal
import sys
from   textwrap                 import dedent
import traceback
from   typing                   import List


from   pyflyby._file            import (FileText, Filename, atomic_write_file,
                                        expand_py_files_from_args, read_file)
from   pyflyby._importstmt      import ImportFormatParams
from   pyflyby._log             import logger
from   pyflyby._util            import cached_attribute, indent

if sys.version_info < (3, 11):
    from tomli import loads
else:
    from tomllib import loads


class ConfigurationError(Exception):
    """Exception class indicating a configuration error."""


def hfmt(s):
    return dedent(s).strip()

def maindoc():
    import __main__
    return (__main__.__doc__ or '').strip()


def _sigpipe_handler(*args):
    # The parent process piped our stdout and closed the pipe before we
    # finished writing, e.g. "tidy-imports ... | head" or "tidy-imports ... |
    # less".  Exit quietly - squelch the "close failed in file object
    # destructor" message would otherwise be raised.
    raise SystemExit(1)


def parse_args(addopts=None, import_format_params=False, modify_action_params=False):
    """
    Do setup for a top-level script and parse arguments.
    """
    ### Setup.
    # Register a SIGPIPE handler.
    signal.signal(signal.SIGPIPE, _sigpipe_handler)
    ### Parse args.
    parser = optparse.OptionParser(usage='\n'+maindoc())

    def log_level_callbacker(level):
        def callback(option, opt_str, value, parser):
            logger.set_level(level)
        return callback

    def debug_callback(option, opt_str, value, parser):
        logger.set_level("DEBUG")

    parser.add_option("--debug", action="callback",
                      callback=debug_callback,
                      help="Debug mode (noisy and fail fast).")

    parser.add_option("--verbose", action="callback",
                      callback=log_level_callbacker("DEBUG"),
                      help="Be noisy.")

    parser.add_option("--quiet", action="callback",
                      callback=log_level_callbacker("ERROR"),
                      help="Be quiet.")

    parser.add_option("--version", action="callback",
                      callback=lambda *args: print_version_and_exit(),
                      help="Print pyflyby version and exit.")

    if modify_action_params:
        group = optparse.OptionGroup(parser, "Action options")
        action_diff = action_external_command('pyflyby-diff')
        def parse_action(v):
            V = v.strip().upper()
            if V == 'PRINT':
                return action_print
            elif V == 'REPLACE':
                return action_replace
            elif V == 'QUERY':
                return action_query()
            elif V == "DIFF":
                return action_diff
            elif V.startswith("QUERY:"):
                return action_query(v[6:])
            elif V.startswith("EXECUTE:"):
                return action_external_command(v[8:])
            elif V == "IFCHANGED":
                return action_ifchanged
            elif V == "EXIT1":
                return action_exit1
            elif V == "CHANGEDEXIT1":
                return action_changedexit1
            else:
                raise Exception(
                    "Bad argument %r to --action; "
                    "expected PRINT or REPLACE or QUERY or IFCHANGED or EXIT1 "
                    "or CHANGEDEXIT1 or EXECUTE:..." % (v,)
                )

        def set_actions(actions):
            actions = tuple(actions)
            parser.values.actions = actions

        def action_callback(option, opt_str, value, parser):
            action_args = value.split(',')
            set_actions([parse_action(v) for v in action_args])

        def action_callbacker(actions):
            def callback(option, opt_str, value, parser):
                set_actions(actions)
            return callback

        group.add_option(
            "--actions", type='string', action='callback',
            callback=action_callback,
            metavar="PRINT|REPLACE|IFCHANGED|QUERY|DIFF|EXIT1|CHANGEDEXIT1:EXECUTE:mycommand",
            help=hfmt(
                """
                   Comma-separated list of action(s) to take.  If PRINT, print
                   the changed file to stdout.  If REPLACE, then modify the
                   file in-place.  If EXECUTE:mycommand, then execute
                   'mycommand oldfile tmpfile'.  If DIFF, then execute
                   'pyflyby-diff'.  If QUERY, then query user to continue.
                   If IFCHANGED, then continue actions only if file was
                   changed.  If EXIT1, then exit with exit code 1 after all
                   files/actions are processed.  If CHANGEDEXIT1, then exit
                   with exit code 1 if any file was changed."""
            ),
        )
        group.add_option(
            "--print", "-p", action='callback',
            callback=action_callbacker([action_print]),
            help=hfmt('''
                Equivalent to --action=PRINT (default when stdin or stdout is
                not a tty) '''))
        group.add_option(
            "--diff", "-d", action='callback',
            callback=action_callbacker([action_diff]),
            help=hfmt('''Equivalent to --action=DIFF'''))
        group.add_option(
            "--replace", "-r", action='callback',
            callback=action_callbacker([action_ifchanged, action_replace]),
            help=hfmt('''Equivalent to --action=IFCHANGED,REPLACE'''))
        group.add_option(
            "--diff-replace", "-R", action='callback',
            callback=action_callbacker([action_ifchanged, action_diff, action_replace]),
            help=hfmt('''Equivalent to --action=IFCHANGED,DIFF,REPLACE'''))
        actions_interactive = [
            action_ifchanged, action_diff,
            action_query("Replace {filename}?"), action_replace]
        group.add_option(
            "--interactive", "-i", action='callback',
            callback=action_callbacker(actions_interactive),
            help=hfmt('''
               Equivalent to --action=IFCHANGED,DIFF,QUERY,REPLACE (default
               when stdin & stdout are ttys) '''))
        if os.isatty(0) and os.isatty(1):
            default_actions = actions_interactive
        else:
            default_actions = [action_print]
        parser.set_default('actions', tuple(default_actions))
        parser.add_option_group(group)

        parser.add_option(
            '--symlinks', action='callback', nargs=1, type=str,
            dest='symlinks', callback=symlink_callback, help="--symlinks should be one of: " + symlinks_help,
        )
        parser.set_defaults(symlinks='error')

    if import_format_params:
        group = optparse.OptionGroup(parser, "Pretty-printing options")
        group.add_option('--align-imports', '--align', type='str', default="32",
                         metavar='N',
                         help=hfmt('''
                             Whether and how to align the 'import' keyword in
                             'from modulename import aliases...'.  If 0, then
                             don't align.  If 1, then align within each block
                             of imports.  If an integer > 1, then align at
                             that column, wrapping with a backslash if
                             necessary.  If a comma-separated list of integers
                             (tab stops), then pick the column that results in
                             the fewest number of lines total per block.'''))
        group.add_option('--from-spaces', type='int', default=3, metavar='N',
                         help=hfmt('''
                             The number of spaces after the 'from' keyword.
                             (Must be at least 1; default is 3.)'''))
        group.add_option('--separate-from-imports', action='store_true',
                         default=False,
                         help=hfmt('''
                             Separate 'from ... import ...'
                             statements from 'import ...' statements.'''))
        group.add_option('--no-separate-from-imports', action='store_false',
                         dest='separate_from_imports',
                         help=hfmt('''
                            (Default) Don't separate 'from ... import ...'
                            statements from 'import ...' statements.'''))
        group.add_option('--align-future', action='store_true',
                         default=False,
                         help=hfmt('''
                             Align the 'from __future__ import ...' statement
                             like others.'''))
        group.add_option('--no-align-future', action='store_false',
                         dest='align_future',
                         help=hfmt('''
                             (Default) Don't align the 'from __future__ import
                             ...' statement.'''))
        group.add_option('--width', type='int', default=None, metavar='N',
                         help=hfmt('''
                             Maximum line length (default: 79).'''))
        group.add_option('--black', action='store_true', default=False,
                         help=hfmt('''
                             Use black to format imports. If this option is
                             used, all other formatting options are ignored,
                             except width'''))
        group.add_option('--hanging-indent', type='choice', default='never',
                         choices=['never','auto','always'],
                         metavar='never|auto|always',
                         dest='hanging_indent',
                         help=hfmt('''
                             How to wrap import statements that don't fit on
                             one line.
                             If --hanging-indent=always, then always indent
                             imported tokens at column 4 on the next line.
                             If --hanging-indent=never (default), then align
                             import tokens after "import (" (by default column
                             40); do so even if some symbols are so long that
                             this would exceed the width (by default 79)).
                             If --hanging-indent=auto, then use hanging indent
                             only if it is necessary to prevent exceeding the
                             width (by default 79).
                         '''))
        group.add_option('--uniform', '-u', action="store_true",
                         help=hfmt('''
                             (Default) Shortcut for --no-separate-from-imports
                             --from-spaces=3 --align-imports=32.'''))
        group.add_option('--unaligned', '-n', action="store_true",
                         help=hfmt('''
                             Shortcut for --separate-from-imports
                             --from-spaces=1 --align-imports=0.'''))

        parser.add_option_group(group)

    if addopts is not None:
        addopts(parser)
    # This is the only way to provide a default value for an option with a
    # callback.
    if modify_action_params:
        args = ["--symlinks=error"] + sys.argv[1:]
    else:
        args = None

    options, args = parser.parse_args(args=args)

    # Set these manually rather than in a callback option because callback
    # options don't get triggered by OptionParser.set_default (which is
    # used when setting values via pyproject.toml)
    if getattr(options, "unaligned", False):
        parser.values.separate_from_imports = True
        parser.values.from_spaces = 1
        parser.values.align_imports = '0'

    if getattr(options, "uniform", False):
        parser.values.separate_from_imports = False
        parser.values.from_spaces = 3
        parser.values.align_imports = '32'

    if import_format_params:
        align_imports_args = [int(x.strip())
                              for x in options.align_imports.split(",")]
        if len(align_imports_args) == 1 and align_imports_args[0] == 1:
            align_imports = True
        elif len(align_imports_args) == 1 and align_imports_args[0] == 0:
            align_imports = False
        else:
            align_imports = tuple(sorted(set(align_imports_args)))
        options.params = ImportFormatParams(
            align_imports         =align_imports,
            from_spaces           =options.from_spaces,
            separate_from_imports =options.separate_from_imports,
            max_line_length       =options.width,
            use_black             =options.black,
            align_future          =options.align_future,
            hanging_indent        =options.hanging_indent,
            )
    return options, args


def _default_on_error(filename):
    raise SystemExit("bad filename %s" % (filename,))


def filename_args(args: List[str], on_error=_default_on_error):
    """
    Return list of filenames given command-line arguments.

    :rtype:
      ``list`` of `Filename`
    """
    if args:
        for a in args:
            assert isinstance(a, str)
        return expand_py_files_from_args([Filename(f) for f in args], on_error)
    elif not os.isatty(0):
        return [Filename.STDIN]
    else:
        syntax()


def print_version_and_exit(extra=None):
    from pyflyby._version import __version__
    msg = "pyflyby %s" % (__version__,)
    progname = os.path.realpath(sys.argv[0])
    if os.path.exists(progname):
        msg += " (%s)" % (os.path.basename(progname),)
    print(msg)
    if extra:
        print(extra)
    raise SystemExit(0)


def syntax(message=None, usage=None):
    if message:
        logger.error(message)
    outmsg = ((usage or maindoc()) +
              '\n\nFor usage, see: %s --help' % (sys.argv[0],))
    print(outmsg, file=sys.stderr)
    raise SystemExit(1)


class AbortActions(Exception):
    pass


class Exit1(Exception):
    pass


class Modifier(object):
    def __init__(self, modifier, filename):
        self.modifier = modifier
        self.filename = filename
        self._tmpfiles = []

    @cached_attribute
    def input_content(self):
        return read_file(self.filename)

    # TODO: refactor to avoid having these heavy-weight things inside a
    # cached_attribute, which causes annoyance while debugging.
    @cached_attribute
    def output_content(self):
        return FileText(self.modifier(self.input_content), filename=self.filename)

    def _tempfile(self):
        from tempfile import NamedTemporaryFile
        f = NamedTemporaryFile()
        self._tmpfiles.append(f)
        return f, Filename(f.name)


    @cached_attribute
    def output_content_filename(self):
        f, fname = self._tempfile()
        f.write(bytes(self.output_content.joined, "utf-8"))
        f.flush()
        return fname

    @cached_attribute
    def input_content_filename(self):
        if isinstance(self.filename, Filename):
            return self.filename
        # If the input was stdin, and the user wants a diff, then we need to
        # write it to a temp file.
        f, fname = self._tempfile()
        f.write(bytes(self.input_content, "utf-8"))
        f.flush()
        return fname


    def __del__(self):
        for f in self._tmpfiles:
            f.close()


def process_actions(filenames:List[str], actions, modify_function,
                    reraise_exceptions=(), exclude=()):

    if not isinstance(exclude, (list, tuple)):
        raise ConfigurationError(
            "Exclusions must be a list of filenames/patterns to exclude."
        )

    errors = []
    def on_error_filename_arg(arg):
        print("%s: bad filename %s" % (sys.argv[0], arg), file=sys.stderr)
        errors.append("%s: bad filename" % (arg,))
    filename_objs = filename_args(filenames, on_error=on_error_filename_arg)
    exit_code = 0
    for filename in filename_objs:

        # Log any matching exclusion patterns before ignoring, if applicable
        matching_excludes = []
        for pattern in exclude:
            if Path(str(filename)).match(str(pattern)):
                matching_excludes.append(pattern)
        if any(matching_excludes):
            msg = f"{filename} matches exclusion pattern"
            if len(matching_excludes) == 1:
                msg += f": {matching_excludes[0]}"
            else:
                msg += f"s: {matching_excludes}"
            logger.info(msg)
            continue

        try:
            m = Modifier(modify_function, filename)
            for action in actions:
                action(m)
        except AbortActions:
            continue
        except reraise_exceptions:
            raise
        except Exit1:
            exit_code = 1
        except Exception as e:
            errors.append("%s: %s: %s" % (filename, type(e).__name__, e))
            type_e = type(e)
            try:
                tb = sys.exc_info()[2]
                if str(filename) not in str(e):
                    try:
                        e = type_e("While processing %s: %s" % (filename, e))
                        pass
                    except TypeError:
                        # Exception takes more than one argument
                        pass
                if logger.debug_enabled:
                    raise
                traceback.print_exception(type(e), e, tb)
            finally:
                tb = None # avoid refcycles involving tb
            continue
    if errors:
        msg = "\n%s: encountered the following problems:\n" % (sys.argv[0],)
        for er in errors:
            lines = er.splitlines()
            msg += "    " + lines[0] + '\n'.join(
                ("            %s"%line for line in lines[1:]))
        raise SystemExit(msg)
    else:
        raise SystemExit(exit_code)


def action_print(m):
    output_content = m.output_content
    sys.stdout.write(output_content.joined)


def action_ifchanged(m):
    if m.output_content.joined == m.input_content.joined:
        logger.debug("unmodified: %s", m.filename)
        raise AbortActions


def action_replace(m):
    if m.filename == Filename.STDIN:
        raise Exception("Can't replace stdio in-place")
    if m.output_content.joined != m.input_content.joined:
        logger.info("%s: *** modified ***", m.filename)
    else:
        logger.debug("%s: *** no modification necessary ***", m.filename)
    atomic_write_file(m.filename, m.output_content)


def action_exit1(m):
    logger.debug("action_exit1")
    raise Exit1


def action_changedexit1(m):
    """Exit with code 1 if there were changes."""
    if m.output_content.joined != m.input_content.joined:
        logger.debug("file changed: %s", m.filename)
        raise Exit1


def action_external_command(command):
    import subprocess
    def action(m):
        bindir = os.path.dirname(os.path.realpath(sys.argv[0]))
        env = os.environ
        env['PATH'] = env['PATH'] + ":" + bindir
        fullcmd = "%s %s %s" % (
            command, m.input_content_filename, m.output_content_filename)
        logger.debug("Executing external command: %s", fullcmd)
        ret = subprocess.call(fullcmd, shell=True, env=env)
        logger.debug("External command returned %d", ret)
    return action


def action_query(prompt="Proceed?"):
    def action(m):
        p = prompt.format(filename=m.filename)
        print()
        print("%s [y/N] " % (p), end="")
        try:
            if input().strip().lower().startswith('y'):
                return True
        except KeyboardInterrupt:
            print("KeyboardInterrupt", file=sys.stderr)
            raise SystemExit(1)
        print("Aborted")
        raise AbortActions
    return action

def symlink_callback(option, opt_str, value, parser):
    parser.values.actions = tuple(
        i for i in parser.values.actions if i not in symlink_callbacks.values()
    )
    if value in symlink_callbacks:
        parser.values.actions = (symlink_callbacks[value],) + parser.values.actions
    else:
        raise optparse.OptionValueError("--symlinks must be one of 'error', 'follow', 'skip', or 'replace'. Got %r" % value)

symlinks_help = """\
--symlinks=error (default; gives an error on symlinks),
--symlinks=follow (follows symlinks),
--symlinks=skip (skips symlinks),
--symlinks=replace (replaces symlinks with the target file\
"""

# Warning, the symlink actions will only work if they are run first.
# Otherwise, output_content may already be cached
def symlink_error(m):
    if m.filename == Filename.STDIN:
        return symlink_follow(m)
    if m.filename.islink:
        raise SystemExit("""\
Error: %s appears to be a symlink. Use one of the following options to allow symlinks:
%s
""" % (m.filename, indent(symlinks_help, '    ')))

def symlink_follow(m):
    if m.filename == Filename.STDIN:
        return
    if m.filename.islink:
        logger.info("Following symlink %s" % m.filename)
        m.filename = m.filename.realpath

def symlink_skip(m):
    if m.filename == Filename.STDIN:
        return symlink_follow(m)
    if m.filename.islink:
        logger.info("Skipping symlink %s" % m.filename)
        raise AbortActions

def symlink_replace(m):
    if m.filename == Filename.STDIN:
        return symlink_follow(m)
    if m.filename.islink:
        logger.info("Replacing symlink %s" % m.filename)
        # The current behavior automatically replaces symlinks, so do nothing

symlink_callbacks = {
    'error': symlink_error,
    'follow': symlink_follow,
    'skip': symlink_skip,
    'replace': symlink_replace,
}

def _get_pyproj_toml_file():
    """Try to find the location of the current project pyproject.toml
    in cwd or parents directories.

    If no pyproject.toml can be found, None is returned.
    """
    cwd = Path(os.getcwd())

    for pth in [cwd] + list(cwd.parents):
        pyproj_toml = pth /'pyproject.toml'
        if pyproj_toml.exists() and pyproj_toml.is_file():
            return pyproj_toml

    return None

def _get_pyproj_toml_config():
    """Return the toml contents of the current pyproject.toml.

    If no pyproject.toml can be found in cwd or parent directories,
    None is returned.
    """
    pyproject_toml = _get_pyproj_toml_file()
    if pyproject_toml is not None:
        return loads(pyproject_toml.read_text())
    return None
