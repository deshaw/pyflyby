
from __future__ import absolute_import, division, with_statement

import os
import re
import sys

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
        if not filename:
            raise UnsafeFilenameError("(empty string)")
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
        if not isinstance(o, Filename):
            return NotImplemented
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


Filename.STDIN = Filename("/dev/stdin")


class FileText(object):
    """
    Represents a contiguous sequence of lines from a file.
    """

    def __new__(cls, arg, filename=None, lineno=None, colno=None):
        """
        Return a new C{FileText} instance.

        @type arg:
          C{FileText}, C{Filename}, C{str}, or tuple of C{str}
        @param arg:
          If a sequence of lines, then each should end with a newline and have
          no other newlines.  Otherwise, something that can be interpreted or
          converted into a sequence of lines.
        @type filename:
          L{Filename}
        @param filename:
          Filename to attach to this C{FileText}, if not already given by
          C{arg}.
        @type lineno:
          C{int}
        @param lineno:
          Value to attach as the line number of the first line in this
          C{FileText}, if not already given by C{arg}.  1-based.
        @type colno:
          C{int}
        @param colno:
          Value to attach as the column number of the first line in this
          C{FileText}, if not already given by C{arg}.  1-based.  Subsequent
          lines always start at column 1.
        @rtype:
          C{FileText}
        """
        if isinstance(arg, cls):
            if filename is lineno is colno is None:
                return arg
            return arg.alter(filename=filename, lineno=lineno)
        elif isinstance(arg, Filename):
            return cls(read_file(arg), filename=filename, lineno=lineno,
                       colno=colno)
        elif hasattr(arg, "__text__"):
            return FileText(arg.__text__(), filename=filename)
        if isinstance(arg, (tuple, list)):
            if not all(isinstance(x, str) for x in arg[:2] + arg[-2:]):
                raise TypeError("%s: unexpected sequence of %s"
                                % (cls.__name__, type(arg[0]).__name__))
            self = object.__new__(cls)
            self.lines = arg
        elif isinstance(arg, basestring):
            self = object.__new__(cls)
            if not arg.endswith("\n"):
                arg += "\n"
            self.joined = arg
        else:
            raise TypeError("%s: unexpected %s"
                            % (cls.__name__, type(arg).__name__))
        if filename is not None:
            filename = Filename(filename)
        if lineno is None:
            lineno = 1
        if colno is None:
            colno = 1
        self.filename = filename
        self.lineno   = lineno
        self.colno    = colno
        return self

    @cached_attribute
    def lines(self): # used if only initialized with 'joined'
        return self.joined.splitlines(True)

    @cached_attribute
    def joined(self): # used if only initialized with 'lines'
        return ''.join(self.lines)

    @classmethod
    def from_filename(cls, filename):
        return cls.from_lines(Filename(filename))

    def alter(self, filename=None, lineno=None, colno=None):
        if filename is not None:
            filename = Filename(filename)
        else:
            filename = self.filename
        if lineno is not None:
            lineno = int(lineno)
        else:
            lineno = self.lineno
        if colno is not None:
            colno = int(colno)
        else:
            colno = self.colno
        if (filename == self.filename and
            lineno == self.lineno and
            colno == self.colno):
            return self
        else:
            result = object.__new__(type(self))
            result.lines    = self.lines
            result.joined   = self.joined
            result.filename = filename
            result.lineno   = lineno
            result.colno    = colno
            return result

    @cached_attribute
    def end_lineno(self):
        """
        The number of the line after the lines contained in self.
        """
        return self.lineno + len(self.lines)

    def _lineno_to_index(self, lineno):
        lineindex = lineno - self.lineno
        if not 0 <= lineindex <= len(self.lines):
            raise ValueError(
                "Line number %d out of range [%d, %d)"
                % (lineno, self.lineno, self.end_lineno))
        return lineindex

    def _colno_to_index(self, lineindex, colno):
        coloffset = self.colno if lineindex == 0 else 1
        colindex = colno - coloffset
        linelen = len(self.lines[lineindex])
        if not 0 <= colindex <= linelen:
            raise ValueError(
                "Column number %d on line %d out of range [%d, %d)"
                % (colno, lineindex+self.lineno, coloffset, coloffset+linelen))
        return colindex

    def __getitem__(self, arg):
        """
        Return the line(s) with the given line number(s).
        If slicing, returns an instance of C{FileText}.

        Note that line numbers are indexed based on C{self.lineno} (which
        is 1 at the start of the file).

          >>> FileText("a\\nb\\nc\\nd")[2]
          'b\\n'

          >>> FileText("a\\nb\\nc\\nd")[2:4]
          FileText('b\\nc\\n', lineno=2)

          >>> FileText("a\\nb\\nc\\nd")[0]
          Traceback (most recent call last):
            ...
          ValueError: Line number 0 out of range [1, 5)

        The index argument can also be given as (lineno, colno) tuples.
        C{colno} is 1-indexed at the start of the file.  For the end of the
        range, if C{colno} is given, then the C{lineno} is an inclusive value.

        @rtype:
          C{str} or L{FileText}
        """
        L = self._lineno_to_index
        C = self._colno_to_index
        if isinstance(arg, slice):
            if arg.step is not None and arg.step != 1:
                raise ValueError("steps not supported")
            # Interpret start (lineno,colno) into indexes.
            if arg.start is None:
                start_lineindex = 0
                start_colindex = 0
            elif isinstance(arg.start, int):
                start_lineindex = L(arg.start)
                start_colindex = 0
            else:
                start_lineno, start_colno = arg.start
                start_lineno = int(start_lineno)
                start_colno  = int(start_colno)
                start_lineindex = L(start_lineno)
                start_colindex = C(start_lineindex, start_colno)
            # Interpret stop (lineno,colno) into indexes.
            if arg.stop is None:
                stop_lineindex = len(self.lines)
                stop_colindex = len(self.lines[-1])
            elif isinstance(arg.stop, int):
                stop_lineindex = L(arg.stop)
                stop_colindex = len(self.lines[stop_lineindex-1])
            else:
                # Interpret (lineno, colno) end of range.
                # Unlike the lineno-only case, we interpret the input argument
                # lineno as an inclusive (closed-ended) endpoint.
                stop_lineno, stop_colno = arg.stop
                stop_lineindex = L(stop_lineno) + 1
                stop_colindex = C(stop_lineindex-1, stop_colno)
            # {start,stop}_{lineindex,colindex} are now 0-indexed
            # [open,closed) ranges.  Note that C{FileText} instances have to
            # have at least one line in them.
            assert 0 <= start_lineindex < stop_lineindex <= len(self.lines)
            assert 0 <= start_colindex < len(self.lines[start_lineindex])
            assert 0 <= stop_colindex <= len(self.lines[stop_lineindex-1])
            # Optimization: return entire range
            if (start_lineindex == 0 and stop_lineindex == len(self.lines) and
                start_colindex == 0 and stop_colindex == len(self.lines[-1])):
                return self
            # Get the lines we care about.
            result_split = self.lines[start_lineindex:stop_lineindex]
            # Clip the starting and ending strings.  We do the end clip first
            # in case the result has only one line.
            result_split[-1] = result_split[-1][:stop_colindex]
            result_split[0] = result_split[0][start_colindex:]
            # Compute the new starting line and column numbers.
            result_lineno = start_lineindex + self.lineno
            if start_lineindex == 0:
                result_colno = start_colindex + self.colno
            else:
                result_colno = start_colindex + 1
            return type(self)(result_split, filename=self.filename,
                              lineno=result_lineno, colno=result_colno)
        elif isinstance(arg, int):
            # Return a single line.
            return self.lines[L(arg)]
        else:
            raise TypeError("bad type %r" % (type(arg),))

    @classmethod
    def concatenate(cls, args):
        """
        Concatenate a bunch of L{FileText} arguments.  Uses the C{filename}
        and C{lineno} from the first argument.

        @rtype:
          L{FileText}
        """
        args = [FileText(x) for x in args]
        if len(args) == 1:
            return args[0]
        return FileText(
            ''.join([l.joined for l in args]),
            filename=args[0].filename,
            lineno=args[0].lineno)

    def __repr__(self):
        r = "%s(%r" % (type(self).__name__, self.joined,)
        if self.filename is not None:
            r += ", filename=%r" % (str(self.filename),)
        if self.lineno != 1:
            r += ", lineno=%d" % (self.lineno,)
        r += ")"
        return r

    def __eq__(self, o):
        return self.filename == o.filename and self.joined == o.joined

    def __cmp__(self, o):
        return cmp((self.filename, self.joined),
                   (o.filename, o.joined))

    def __hash__(self):
        return hash((self.filename, self.joined))


def read_file(filename):
    filename = Filename(filename)
    if filename == Filename.STDIN:
        data = sys.stdin.read()
    else:
        with open(str(filename), 'rU') as f:
            data = f.read()
    return FileText(data, filename=filename)

def write_file(filename, data):
    filename = Filename(filename)
    data = FileText(data)
    with open(str(filename), 'w') as f:
        f.write(data.joined)

def atomic_write_file(filename, data):
    filename = Filename(filename)
    data = FileText(data)
    temp_filename = Filename("%s.tmp.%s" % (filename, os.getpid(),))
    write_file(temp_filename, data)
    try:
        st = os.stat(str(filename)) # OSError if file didn't exit before
        os.chmod(str(temp_filename), st.st_mode)
        os.chown(str(temp_filename), -1, st.st_gid) # OSError if not member of group
    except OSError:
        pass
    os.rename(str(temp_filename), str(filename))
