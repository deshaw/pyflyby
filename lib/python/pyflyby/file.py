
from __future__ import absolute_import, division, with_statement

import errno
import os
import re
import sys

from   pyflyby.log              import logger
from   pyflyby.util             import cached_attribute

class UnsafeFilenameError(ValueError):
    pass

class Filename(object):
    """
    A filename.
    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, basestring):
            return cls.from_filename(arg)
        raise TypeError

    @classmethod
    def from_filename(cls, filename):
        if not isinstance(filename, basestring):
            raise TypeError
        filename = str(filename)
        if re.search("[^a-zA-Z0-9_=+{}/.,~-]", filename):
            raise UnsafeFilenameError(filename)
        if re.search("(^|/)~", filename):
            raise UnsafeFilenameError(filename)
        self = object.__new__(cls)
        self._filename = os.path.abspath(filename)
        return self

    def __str__(self):
        return self._filename

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self._filename)

    def __truediv__(self, x):
        return type(self)(os.path.join(self._filename, x))

    def __cmp__(self, o):
        o = type(self)(o)
        return cmp(self._filename, o._filename)

    @cached_attribute
    def ext(self):
        """
        Returns the extension of this filename, including the dot.
        Returns C{None} if no extension.

        @rtype:
          C{str} or C{None}
        """
        lhs, dot, rhs = self._filename.rpartition('.')
        if not dot:
            return None
        return dot + rhs

    @cached_attribute
    def base(self):
        return os.path.basename(self._filename)

    @cached_attribute
    def dir(self):
        return type(self)(os.path.dirname(self._filename))

    @cached_attribute
    def real(self):
        return type(self)(os.path.realpath(self._filename))

    @property
    def exists(self):
        return os.path.exists(self._filename)

    @property
    def isdir(self):
        return os.path.isdir(self._filename)

    @property
    def isfile(self):
        return os.path.isfile(self._filename)

    def list(self):
        return [type(self)(os.path.join(self._filename, f))
                for f in sorted(os.listdir(self._filename))]

    def recursive_iterate(self, ignore_dotfiles=True):
        if ignore_dotfiles and self.base.startswith('.'):
            return
        if self.isfile:
            yield self
        elif self.isdir:
            for child in self.list():
                for rchild in child.recursive_iterate():
                    yield rchild
        # Could be broken symlink, special, etc.

STDIO_PIPE = object() # Singleton token

class FileContents(str):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, str):
            return cls.from_contents(arg)
        if isinstance(arg, Filename):
            return read_file(arg)
        raise TypeError

    @classmethod
    def from_contents(cls, text, filename=None):
        if not isinstance(text, str):
            raise TypeError
        self = str.__new__(cls, text)
        self.filename = filename
        return self

    def __repr__(self):
        s = "%s.from_contents(%r" % (type(self).__name__, str(self))
        if self.filename is not None:
            s += ", %r" % (self.filename,)
        s += ")"
        return s


class FileLines(object):
    """
    Represents a contiguous sequence of lines from a file.
    """

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (Filename, FileContents, str)):
            return cls.from_text(arg)
        raise TypeError

    @classmethod
    def from_lines(cls, lines, filename=None, linenumber=1):
        """
        @type params:
          Sequence of strings, each of which ends with a newline and has no
          other newlines.
        @rtype:
          L{FileLines}
        """
        if isinstance(lines, str):
            raise TypeError
        self = object.__new__(cls)
        self.lines = tuple(lines)
        self.filename = filename
        self.linenumber = linenumber
        return self

    @classmethod
    def from_text(cls, text, linenumber=1):
        text = FileContents(text)
        # Split into physical lines.
        lines = text.splitlines(True)
        self = cls.from_lines(lines, filename=text.filename, linenumber=linenumber)
        self.joined = text # optimization
        return self

    @cached_attribute
    def joined(self):
        return ''.join(self.lines)

    @cached_attribute
    def end_linenumber(self):
        """
        The number of the line after the lines contained in self.
        """
        return self.linenumber + len(self.lines)

    def _linenumber_to_index(self, linenumber):
        if not self.linenumber <= linenumber <= self.end_linenumber:
            raise ValueError(
                "Line number %d out of range [%d, %d)"
                % (linenumber, self.linenumber, self.end_linenumber))
        return linenumber - self.linenumber

    def __getitem__(self, arg):
        """
        Return the line(s) with the given line number(s).
        If slicing, returns an instance of C{FileLines}.

        Note that line numbers are indexed based on C{self.linenumber}.

          >>> FileLines("a\\nb\\nc\\nd")[2]
          'b\\n'

          >>> FileLines("a\\nb\\nc\\nd")[2:4]
          FileLines.from_text('b\\nc\\n', linenumber=2)

          >>> FileLines("a\\nb\\nc\\nd")[0]
          Traceback (most recent call last):
            ...
          ValueError: Line number 0 out of range [1, 5)

        @rtype:
          C{str} or L{FileLines}
        """
        N = self._linenumber_to_index
        if isinstance(arg, slice):
            if arg.step is not None and arg.step != 1:
                raise ValueError("steps not supported")
            return type(self).from_lines(
                self.lines[N(arg.start):N(arg.stop)],
                self.filename, arg.start)
        elif isinstance(arg, int):
            return self.lines[N(arg)]
        else:
            raise TypeError("bad type %r" % (type(arg),))

    def __repr__(self):
        if self.filename is None:
            d = self.joined
        else:
            d = FileContents.from_contents(self.joined, self.filename)
        return "%s.from_text(%r, linenumber=%r)" % (
            type(self).__name__, d, self.linenumber)


def read_file(filename):
    if filename is STDIO_PIPE:
        return FileContents.from_contents(
            sys.stdin.read(), filename="(stdin)")
    filename = Filename(filename)
    with open(str(filename)) as f:
        return FileContents.from_contents(f.read(), filename=filename)

def write_file(filename, data):
    filename = Filename(filename)
    data = FileContents(data)
    with open(str(filename), 'w') as f:
        f.write(data)

def atomic_write_file(filename, data):
    filename = Filename(filename)
    data = FileContents(data)
    temp_filename = Filename("%s.tmp.%s" % (filename, os.getpid(),))
    write_file(temp_filename, data)
    try:
        st = os.stat(str(filename)) # OSError if file didn't exit before
        os.chmod(str(temp_filename), st.st_mode)
        os.chown(str(temp_filename), -1, st.st_gid) # OSError if not member of group
    except OSError:
        pass
    os.rename(str(temp_filename), str(filename))

def modify_file(filename, modifier):
    """
    Modify C{filename} using C{modifier}.

    @param modifier:
      Function that takes a L{FileContents} and returns a L{FileContents}.
    """
    if filename is STDIO_PIPE:
        original = read_file(filename)
        modified = FileContents(modifier(original))
        try:
            sys.stdout.write(modified)
            # Explicitly (try to) close here, so that we can catch EPIPE
            # here.  Otherwise we get an ugly error message at system exit.
            sys.stdout.close()
        except IOError as e:
            # Quietly exit if pipe closed.
            if e.errno == errno.EPIPE:
                raise SystemExit(1)
            raise
        return
    filename = Filename(filename)
    original = read_file(filename)
    modified = FileContents(modifier(original))
    if modified != original:
        logger.info("%s: *** modified ***", filename)
        atomic_write_file(filename, modified)
        return True
    else:
        logger.debug("%s: (unchanged)", filename)
        return False
