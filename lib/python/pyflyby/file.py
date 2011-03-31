
from __future__ import absolute_import, division, with_statement

import os
import re

from pyflyby.util import cached_attribute

class UnsafeFilenameError(ValueError):
    pass

class Filename(object):
    """
    A filename.
    """
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, str):
            return cls.from_filename(arg)
        raise TypeError

    @classmethod
    def from_filename(cls, filename):
        if not isinstance(filename, str):
            raise TypeError
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

def read_file(filename):
    filename = Filename(filename)
    with open(str(filename)) as f:
        return f.read()

def write_file(filename, data):
    filename = Filename(filename)
    with open(str(filename), 'w') as f:
        f.write(data)

def atomic_write_file(filename, data):
    filename = Filename(filename)
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
      Function that takes a C{str} and returns a C{str}.
    """
    filename = Filename(filename)
    original = read_file(filename)
    modified = modifier(original)
    if modified != original:
        print "%s modified" % (filename,)
        atomic_write_file(filename, modified)
        return True
    else:
        print "%s unchanged" % (filename,)
        return False
