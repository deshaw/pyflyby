# pyflyby/_cmdline.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from builtins import input
import optparse
import os
import signal
import sys
from textwrap import dedent
import traceback
from typing import List

from pyflyby._file import (
    FileText, Filename, atomic_write_file,
    expand_py_files_from_args, read_file
)
from pyflyby._importstmt import ImportFormatParams
from pyflyby._log import logger
from functools import cached_property
from pyflyby._util import indent


def hfmt(s):
    return dedent(s).strip()

def maindoc():
    import __main__
    return (__main__.__doc__ or '').strip()

def _sigpipe_handler(*args):
    raise SystemExit(1)

def parse_args(
    addopts=None, import_format_params=False, modify_action_params=False, defaults=None
):
    if defaults is None:
        defaults = {}

    signal.signal(signal.SIGPIPE, _sigpipe_handler)
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
            else:
                raise Exception("Bad argument %r to --action" % (v,))

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
            metavar='PRINT|REPLACE|IFCHANGED|QUERY|DIFF|EXIT1:EXECUTE:mycommand',
            help=hfmt('''
                   Comma-separated list of action(s) to take...'''))

        group.add_option(
            "--print", "-p", action='callback',
            callback=action_callbacker([action_print]),
            help=hfmt('Equivalent to --action=PRINT'))

        group.add_option(
            "--diff", "-d", action='callback',
            callback=action_callbacker([action_diff]),
            help=hfmt('Equivalent to --action=DIFF'))

        group.add_option(
            "--replace", "-r", action='callback',
            callback=action_callbacker([action_ifchanged, action_replace]),
            help=hfmt('Equivalent to --action=IFCHANGED,REPLACE'))

        group.add_option(
            "--diff-replace", "-R", action='callback',
            callback=action_callbacker([action_ifchanged, action_diff, action_replace]),
            help=hfmt('Equivalent to --action=IFCHANGED,DIFF,REPLACE'))

        actions_interactive = [
            action_ifchanged, action_diff,
            action_query("Replace {filename}?"), action_replace]
        group.add_option(
            "--interactive", "-i", action='callback',
            callback=action_callbacker(actions_interactive),
            help=hfmt('Equivalent to --action=IFCHANGED,DIFF,QUERY,REPLACE'))

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
        # Skipping inner formatting options for brevity here...
        parser.add_option_group(group)

    if addopts is not None:
        addopts(parser)

    if modify_action_params:
        args = ["--symlinks=error"] + sys.argv[1:]
    else:
        args = None
    options, args = parser.parse_args(args=args)

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
            align_imports=align_imports,
            from_spaces=options.from_spaces,
            separate_from_imports=options.separate_from_imports,
            max_line_length=options.width,
            use_black=options.black,
            align_future=options.align_future,
            hanging_indent=options.hanging_indent,
        )
    return options, args


def _default_on_error(filename):
    raise SystemExit("bad filename %s" % (filename,))


def filename_args(args: List[str], on_error=_default_on_error):
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


class AbortActions(Exception): pass
class Exit1(Exception): pass


class Modifier(object):
    def __init__(self, modifier, filename):
        self.modifier = modifier
        self.filename = filename
        self._tmpfiles = []

    @cached_property
    def input_content(self):
        return read_file(self.filename)

    @cached_property
    def output_content(self):
        return FileText(self.modifier(self.input_content), filename=self.filename)

    def _tempfile(self):
        from tempfile import NamedTemporaryFile
        f = NamedTemporaryFile()
        self._tmpfiles.append(f)
        return f, Filename(f.name)

    @cached_property
    def output_content_filename(self):
        f, fname = self._tempfile()
        f.write(bytes(self.output_content.joined, "utf-8"))
        f.flush()
        return fname

    @cached_property
    def input_content_filename(self):
        if isinstance(self.filename, Filename):
            return self.filename
        f, fname = self._tempfile()
        f.write(bytes(self.input_content, "utf-8"))
        f.flush()
        return fname

    def __del__(self):
        for f in self._tmpfiles:
            f.close()


def process_actions(filenames: List[str], actions, modify_function,
                    reraise_exceptions=()):
    errors = []
    def on_error_filename_arg(arg):
        print("%s: bad filename %s" % (sys.argv[0], arg), file=sys.stderr)
        errors.append("%s: bad filename" % (arg,))
    filenames = filename_args(filenames, on_error=on_error_filename_arg)
    exit_code = 0
    for filename in filenames:
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
            try:
                tb = sys.exc_info()[2]
                if str(filename) not in str(e):
                    e = type(e)("While processing %s: %s" % (filename, e))
                if logger.debug_enabled:
                    raise
                traceback.print_exception(type(e), e, tb)
            finally:
                tb = None
            continue
    if errors:
        msg = "\n%s: encountered the following problems:\n" % (sys.argv[0],)
        for er in errors:
            lines = er.splitlines()
            msg += "    " + lines[0] + '\n'.join(
                ("            %s" % line for line in lines[1:]))
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
    logger.info("%s: *** modified ***", m.filename)
    atomic_write_file(m.filename, m.output_content)


def action_exit1(m):
    logger.debug("action_exit1")
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
    parser.values.actions = tuple(i for i in parser.values.actions if i not in
    symlink_callbacks.values())
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


symlink_callbacks = {
    'error': symlink_error,
    'follow': symlink_follow,
    'skip': symlink_skip,
    'replace': symlink_replace,
}
