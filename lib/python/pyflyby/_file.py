# pyflyby/_file.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2015, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT
from __future__ import annotations

from   functools                import cached_property, total_ordering
import io
import os
import re
import sys
from   typing                   import ClassVar, List, Optional, Tuple, Union

from   pyflyby._util            import cmp, memoize

from   types                    import NoneType


class UnsafeFilenameError(ValueError):
    pass


# TODO: statcache

@total_ordering
class Filename(object):
    """
    A filename.

      >>> Filename('/etc/passwd')
      Filename('/etc/passwd')

    """
    _filename: str
    STDIN: Filename

    def __new__(cls, arg):
        if isinstance(arg, cls):
            # TODO make this assert False
            return cls._from_filename(arg._filename)
        if isinstance(arg, str):
            return cls._from_filename(arg)
        raise TypeError

    @classmethod
    def _from_filename(cls, filename: str):
        if not isinstance(filename, str):
            raise TypeError
        filename = os.path.abspath(filename)
        if not filename:
            raise UnsafeFilenameError("(empty string)")
        # we only allow filename with given character set
        match = re.search("[^a-zA-Z0-9_=+{}/.,~@-]", filename)
        if match:
            raise UnsafeFilenameError((filename, match))
        if re.search("(^|/)~", filename):
            raise UnsafeFilenameError(filename)
        self = object.__new__(cls)
        self._filename =  filename
        return self

    def __str__(self):
        return self._filename

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self._filename)

    def __truediv__(self, x):
        return type(self)(os.path.join(self._filename, x))

    def __hash__(self):
        return hash(self._filename)

    def __eq__(self, o):
        if self is o:
            return True
        if not isinstance(o, Filename):
            return NotImplemented
        return self._filename == o._filename

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, o):
        if not isinstance(o, Filename):
            return NotImplemented
        return self._filename < o._filename

    def __cmp__(self, o):
        if self is o:
            return 0
        if not isinstance(o, Filename):
            return NotImplemented
        return cmp(self._filename, o._filename)

    @cached_property
    def ext(self):
        """
        Returns the extension of this filename, including the dot.
        Returns ``None`` if no extension.

        :rtype:
          ``str`` or ``None``
        """
        lhs, dot, rhs = self._filename.rpartition('.')
        if not dot:
            return None
        return dot + rhs

    @cached_property
    def base(self):
        return os.path.basename(self._filename)

    @cached_property
    def dir(self):
        return type(self)(os.path.dirname(self._filename))

    @cached_property
    def real(self):
        return type(self)(os.path.realpath(self._filename))

    @property
    def realpath(self):
        return type(self)(os.path.realpath(self._filename))

    @property
    def exists(self):
        return os.path.exists(self._filename)

    @property
    def islink(self):
        return os.path.islink(self._filename)

    @property
    def isdir(self):
        return os.path.isdir(self._filename)

    @property
    def isfile(self):
        return os.path.isfile(self._filename)

    @property
    def isreadable(self):
        return os.access(self._filename, os.R_OK)

    @property
    def iswritable(self):
        return os.access(self._filename, os.W_OK)

    @property
    def isexecutable(self):
        return os.access(self._filename, os.X_OK)

    def startswith(self, prefix):
        prefix = Filename(prefix)
        if self == prefix:
            return True
        return self._filename.startswith("%s/" % (prefix,))

    def list(self, ignore_unsafe=True):
        filenames = [os.path.join(self._filename, f)
                     for f in sorted(os.listdir(self._filename))]
        result = []
        for f in filenames:
            try:
                f = Filename(f)
            except UnsafeFilenameError:
                if ignore_unsafe:
                    continue
                else:
                    raise
            result.append(f)
        return result

    @property
    def ancestors(self):
        """
        Return ancestors of self, from self to /.

          >>> Filename("/aa/bb").ancestors
          (Filename('/aa/bb'), Filename('/aa'), Filename('/'))

        :rtype:
          ``tuple`` of ``Filename`` s
        """
        result = [self]
        while True:
            dir = result[-1].dir
            if dir == result[-1]:
                break
            result.append(dir)
        return tuple(result)


@memoize
def _get_PATH():
    PATH = os.environ.get("PATH", "").split(os.pathsep)
    result = []
    for path in PATH:
        if not path:
            continue
        try:
            result.append(Filename(path))
        except UnsafeFilenameError:
            continue
    return tuple(result)


def which(program):
    """
    Find ``program`` on $PATH.

    :type program:
      ``str``
    :rtype:
      `Filename`
    :return:
      Program on $PATH, or ``None`` if not found.
    """
    # See if it exists in the current directory.
    candidate = Filename(program)
    if candidate.isreadable:
        return candidate
    for path in _get_PATH():
        candidate = path / program
        if candidate.isexecutable:
            return candidate
    return None



Filename.STDIN = Filename("/dev/stdin")

@total_ordering
class FilePos(object):
    """
    A (lineno, colno) position within a `FileText`.
    Both lineno and colno are 1-indexed.
    """

    lineno: int
    colno: int

    _ONE_ONE: ClassVar[FilePos]

    def __new__(cls, *args):
        if len(args) == 0:
            return cls._ONE_ONE
        if len(args) == 1:
            arg, = args
            if isinstance(arg, cls):
                return arg
            elif arg is None:
                return cls._ONE_ONE
            elif isinstance(arg, tuple):
                args = arg
                # Fall through
            else:
                raise TypeError
        lineno, colno = cls._intint(args)
        if lineno == colno == 1:
            return cls._ONE_ONE # space optimization
        if lineno < 1:
            raise ValueError(
                "FilePos: invalid lineno=%d; should be >= 1" % lineno,)
        if colno < 1:
            raise ValueError(
                "FilePos: invalid colno=%d; should be >= 1" % colno,)
        return cls._from_lc(lineno, colno)

    @staticmethod
    def _intint(args):
        if (type(args) is tuple and
            len(args) == 2 and
            type(args[0]) is type(args[1]) is int):
            return args
        else:
            raise TypeError("Expected (int,int); got %r" % (args,))

    @classmethod
    def _from_lc(cls, lineno:int, colno:int):
        self = object.__new__(cls)
        self.lineno = lineno
        self.colno  = colno
        return self

    def __add__(self, delta):
        '''
        "Add" a coordinate (line,col) delta to this ``FilePos``.

        Note that addition here may be a non-obvious.  If there is any line
        movement, then the existing column number is ignored, and the new
        column is the new column delta + 1 (to convert into 1-based numbers).

        :rtype:
          `FilePos`
        '''
        ldelta, cdelta = self._intint(delta)
        # Invalid position delta: this is known to be triggerd
        # by decorators with whitespace after @ (e.g., '@ foo'),
        # which is valid Python syntax but not currently supported by pyflyby.
        # a knownfail test for this case exists.
        assert ldelta >= 0 and cdelta >= 0
        if ldelta == 0:
            return FilePos(self.lineno, self.colno + cdelta)
        else:
            return FilePos(self.lineno + ldelta, 1 + cdelta)

    def __str__(self):
        return "(%d,%d)" % (self.lineno, self.colno)

    def __repr__(self):
        return "FilePos%s" % (self,)

    @property
    def _data(self):
        return (self.lineno, self.colno)

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, FilePos):
            return NotImplemented
        return self._data == other._data

    def __ne__(self, other):
        return not (self == other)

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, FilePos):
            return NotImplemented
        return cmp(self._data, other._data)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if self is other:
            return 0
        if not isinstance(other, FilePos):
            return NotImplemented
        return self._data < other._data

    def __hash__(self):
        return hash(self._data)



FilePos._ONE_ONE = FilePos._from_lc(1, 1)


@total_ordering
class FileText:
    """
    Represents a contiguous sequence of lines from a file.
    """

    filename: Optional[Filename]
    startpos: FilePos
    _lines: Optional[Tuple[str, ...]] = None

    def __new__(cls, arg, filename=None, startpos=None):
        """
        Return a new ``FileText`` instance.

        :type arg:
          ``FileText``, ``Filename``, ``str``, or tuple of ``str``
        :param arg:
          If a sequence of lines, then each should end with a newline and have
          no other newlines.  Otherwise, something that can be interpreted or
          converted into a sequence of lines.
        :type filename:
          `Filename`
        :param filename:
          Filename to attach to this ``FileText``, if not already given by
          ``arg``.
        :type startpos:
          ``FilePos``
        :param startpos:
          Starting file position (lineno & colno) of this ``FileText``, if not
          already given by ``arg``.
        :rtype:
          ``FileText``
        """
        if isinstance(filename, str):
            filename = Filename(filename)
        if isinstance(arg, cls):
            if filename is startpos is None:
                return arg
            return arg.alter(filename=filename, startpos=startpos)
        elif isinstance(arg, Filename):
            return cls(read_file(arg), filename=filename, startpos=startpos)
        elif hasattr(arg, "__text__"):
            return FileText(arg.__text__(), filename=filename, startpos=startpos)
        elif isinstance(arg, str):
            self = object.__new__(cls)
            self._lines = tuple(arg.split('\n'))
        else:
            raise TypeError("%s: unexpected %s"
                            % (cls.__name__, type(arg).__name__))

        assert isinstance(filename, (Filename, NoneType))
        startpos = FilePos(startpos)
        self.filename = filename
        self.startpos = startpos
        return self

    def get_comments(self) -> list[Optional[str]]:
        """Return the comment string for each line (if any).

        :return:
            The comment string for each line in the statement. If no
            comment is present, None is returned for that line
        """
        comments: list[Optional[str]] = []
        if self._lines:
            for line in self._lines:
                split = line.split("#", maxsplit=1)[1:]
                if split:
                    comments.append(split[0])
                else:
                    comments.append(None)
        return comments

    @classmethod
    def _from_lines(cls, lines, filename: Optional[Filename], startpos: FilePos):
        assert type(lines) is tuple
        assert len(lines) > 0
        assert isinstance(lines[0], str)
        assert not lines[-1].endswith("\n")
        assert isinstance(startpos, FilePos), repr(startpos)
        assert isinstance(filename, (Filename, type(None))), repr(filename)
        self = object.__new__(cls)
        self._lines    = tuple(lines)
        self.filename = filename
        self.startpos = startpos
        return self

    @cached_property
    def lines(self) -> Tuple[str, ...]:
        r"""
        Lines that have been split by newline.

        These strings do NOT contain '\n'.

        If the input file ended in '\n', then the last item will be the empty
        string.  This is to avoid having to check lines[-1].endswith('\n')
        everywhere.

        :rtype:
          ``tuple`` of ``str``
        """
        if self._lines is not None:
            return self._lines
        # Used if only initialized with 'joined'.
        # We use str.split() instead of str.splitlines() because the latter
        # doesn't distinguish between strings that end in newline or not
        # (or requires extra work to process if we use splitlines(True)).
        return tuple(self.joined.split('\n'))

    @cached_property
    def joined(self) -> str:
        return '\n'.join(self.lines)

    @classmethod
    def from_filename(cls, filename):
        return cls.from_lines(Filename(filename))

    def alter(self, filename: Optional[Filename] = None, startpos=None):
        if filename is not None:
            assert isinstance(filename, Filename)
        else:
            filename = self.filename
        if startpos is not None:
            startpos = FilePos(startpos)
        else:
            startpos = self.startpos
        if filename == self.filename and startpos == self.startpos:
            return self
        else:
            result = object.__new__(type(self))
            result._lines   = self._lines
            result.filename = filename
            result.startpos = startpos
            return result

    @cached_property
    def endpos(self):
        """
        The position after the last character in the text.

        :rtype:
          ``FilePos``
        """
        startpos = self.startpos
        lines    = self.lines
        lineno   = startpos.lineno + len(lines) - 1
        if len(lines) == 1:
            colno = startpos.colno + len(lines[-1])
        else:
            colno = 1 + len(lines[-1])
        return FilePos(lineno, colno)

    def _lineno_to_index(self, lineno):
        lineindex = lineno - self.startpos.lineno
        # Check that the lineindex is in range.  We don't allow pointing at
        # the line after the last line because we already ensured that
        # self.lines contains an extra empty string if necessary, to indicate
        # a trailing newline in the file.
        if not 0 <= lineindex < len(self.lines):
            raise IndexError(
                "Line number %d out of range [%d, %d)"
                % (lineno, self.startpos.lineno, self.endpos.lineno))
        return lineindex

    def _colno_to_index(self, lineindex, colno):
        coloffset = self.startpos.colno if lineindex == 0 else 1
        colindex = colno - coloffset
        line = self.lines[lineindex]
        # Check that the colindex is in range.  We do allow pointing at the
        # character after the last (non-newline) character in the line.
        if not 0 <= colindex <= len(line):
            raise IndexError(
                "Column number %d on line %d out of range [%d, %d]"
                % (colno, lineindex+self.startpos.lineno,
                   coloffset, coloffset+len(line)))
        return colindex

    def __getitem__(self, arg):
        """
        Return the line(s) with the given line number(s).
        If slicing, returns an instance of ``FileText``.

        Note that line numbers are indexed based on ``self.startpos.lineno``
        (which is 1 at the start of the file).

          >>> FileText("a\\nb\\nc\\nd")[2]
          'b'

          >>> FileText("a\\nb\\nc\\nd")[2:4]
          FileText('b\\nc\\n', startpos=(2,1))

          >>> FileText("a\\nb\\nc\\nd")[0]
          Traceback (most recent call last):
          ...
          IndexError: Line number 0 out of range [1, 4)

        When slicing, the input arguments can also be given as ``FilePos``
        arguments or (lineno,colno) tuples.  These are 1-indexed at the start
        of the file.

          >>> FileText("a\\nb\\nc\\nd")[(2,2):4]
          FileText('\\nc\\n', startpos=(2,2))

        :rtype:
          ``str`` or `FileText`
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
                startpos = FilePos(arg.start)
                start_lineindex = L(startpos.lineno)
                start_colindex = C(start_lineindex, startpos.colno)
            # Interpret stop (lineno,colno) into indexes.
            if arg.stop is None:
                stop_lineindex = len(self.lines)
                stop_colindex = len(self.lines[-1])
            elif isinstance(arg.stop, int):
                stop_lineindex = L(arg.stop)
                stop_colindex = 0
            else:
                stoppos = FilePos(arg.stop)
                stop_lineindex = L(stoppos.lineno)
                stop_colindex = C(stop_lineindex, stoppos.colno)
            # {start,stop}_{lineindex,colindex} are now 0-indexed
            # [open,closed) ranges.
            assert 0 <= start_lineindex <= stop_lineindex < len(self.lines)
            assert 0 <= start_colindex <= len(self.lines[start_lineindex])
            assert 0 <= stop_colindex <= len(self.lines[stop_lineindex])
            # Optimization: return entire range
            if (start_lineindex == 0 and
                start_colindex == 0 and
                stop_lineindex == len(self.lines)-1 and
                stop_colindex == len(self.lines[-1])):
                return self
            # Get the lines we care about.  We always include an extra entry
            # at the end which we'll chop to the desired number of characters.
            result_split = list(self.lines[start_lineindex:stop_lineindex+1])
            # Clip the starting and ending strings.  We do the end clip first
            # in case the result has only one line.
            result_split[-1] = result_split[-1][:stop_colindex]
            result_split[0] = result_split[0][start_colindex:]
            # Compute the new starting line and column numbers.
            result_lineno = start_lineindex + self.startpos.lineno
            if start_lineindex == 0:
                result_colno = start_colindex + self.startpos.colno
            else:
                result_colno = start_colindex + 1
            result_startpos = FilePos(result_lineno, result_colno)
            return FileText._from_lines(tuple(result_split),
                                        filename=self.filename,
                                        startpos=result_startpos)
        elif isinstance(arg, int):
            # Return a single line.
            lineindex = L(arg)
            return self.lines[lineindex]
        else:
            raise TypeError("bad type %r" % (type(arg),))

    @classmethod
    def concatenate(cls, args):
        """
        Concatenate a bunch of `FileText` arguments.  Uses the ``filename``
        and ``startpos`` from the first argument.

        :rtype:
          `FileText`
        """
        args = [FileText(x) for x in args]
        if len(args) == 1:
            return args[0]
        return FileText(
            ''.join([l.joined for l in args]),
            filename=args[0].filename if args else None,
            startpos=args[0].startpos if args else None)

    def __repr__(self):
        r = "%s(%r" % (type(self).__name__, self.joined,)
        if self.filename is not None:
            r += ", filename=%r" % (str(self.filename),)
        if self.startpos != FilePos():
            r += ", startpos=%s" % (self.startpos,)
        r += ")"
        return r

    def __str__(self):
        return self.joined

    def __eq__(self, o):
        if self is o:
            return True
        if not isinstance(o, FileText):
            return NotImplemented
        return (self.filename == o.filename and
                self.joined   == o.joined   and
                self.startpos == o.startpos)

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, o):
        if not isinstance(o, FileText):
            return NotImplemented
        return ((self.filename, self.joined, self.startpos) <
                   (o   .filename, o   .joined, o   .startpos))

    def __cmp__(self, o):
        if self is o:
            return 0
        if not isinstance(o, FileText):
            return NotImplemented
        return cmp((self.filename, self.joined, self.startpos),
                   (o   .filename, o   .joined, o   .startpos))

    def __hash__(self):
        h = hash((self.filename, self.joined, self.startpos))
        self.__hash__ = lambda: h
        return h


def read_file(filename: Filename) -> FileText:
    assert isinstance(filename, Filename)
    if filename == Filename.STDIN:
        data = sys.stdin.read()
    else:
        with io.open(str(filename), 'r') as f:
            data = f.read()
    return FileText(data, filename=filename)


def write_file(filename: Filename, data):
    assert isinstance(filename, Filename)
    data = FileText(data)
    with open(str(filename), 'w') as f:
        f.write(data.joined)

def atomic_write_file(filename: Filename, data):
    assert isinstance(filename, Filename)
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


def expand_py_files_from_args(
    pathnames: Union[List[Filename], Filename], on_error=lambda filename: None
):
    """
    Enumerate ``*.py`` files, recursively.

    Arguments that are files are always included.
    Arguments that are directories are recursively searched for ``*.py`` files.

    :type pathnames:
      ``list`` of `Filename` s
    :type on_error:
      callable
    :param on_error:
      Function that is called for arguments directly specified in ``pathnames``
      that don't exist or are otherwise inaccessible.
    :rtype:
      ``list`` of `Filename` s
    """
    if not isinstance(pathnames, (tuple, list)):
        # July 2024 DeprecationWarning
        # this seem to be used only internally, maybe deprecate not passing a list.
        pathnames = [pathnames]
    for f in pathnames:
        assert isinstance(f, Filename)
    result = []
    # Check for problematic arguments.  Note that we intentionally only do
    # this for directly specified arguments, not for recursively traversed
    # arguments.
    stack = []
    for pathname in reversed(pathnames):
        if pathname.isfile:
            stack.append((pathname, True))
        elif pathname.isdir:
            stack.append((pathname, False))
        else:
            on_error(pathname)
    while stack:
        pathname, isfile = stack.pop(-1)
        if isfile:
            result.append(pathname)
            continue
        for f in reversed(pathname.list()):
            # Check inclusions/exclusions for recursion.  Note that we
            # intentionally do this in the recursive step rather than the
            # base step because if the user specification includes
            # e.g. .pyflyby, we do want to include it; however, we don't
            # want to recurse into .pyflyby ourselves.
            if f.base.startswith("."):
                continue
            if f.base == "__pycache__":
                continue
            if f.isfile:
                if f.ext == ".py":
                    stack.append((f, True))
            elif f.isdir:
                stack.append((f, False))
            else:
                # Silently ignore non-files/dirs from traversal.
                pass
    return result
