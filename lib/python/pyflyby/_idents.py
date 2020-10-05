# pyflyby/_idents.py.
# Copyright (C) 2011, 2012, 2013, 2014, 2018 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import (absolute_import, division, print_function,
                        with_statement)

from   functools                import total_ordering
from   keyword                  import kwlist
import re
import six

from   pyflyby._util            import cached_attribute, cmp


# Don't consider "print" a keyword, in order to be compatible with user code
# that uses "from __future__ import print_function".
_my_kwlist = list(kwlist)
if six.PY2:
    _my_kwlist.remove("print")
_my_iskeyword = frozenset(_my_kwlist).__contains__


# TODO: use DottedIdentifier.prefixes
def dotted_prefixes(dotted_name, reverse=False):
    """
    Return the prefixes of a dotted name.

      >>> dotted_prefixes("aa.bb.cc")
      ['aa', 'aa.bb', 'aa.bb.cc']

      >>> dotted_prefixes("aa.bb.cc", reverse=True)
      ['aa.bb.cc', 'aa.bb', 'aa']

    :type dotted_name:
      ``str``
    :param reverse:
      If False (default), return shortest to longest.  If True, return longest
      to shortest.
    :rtype:
      ``list`` of ``str``
    """
    name_parts = dotted_name.split(".")
    if reverse:
        idxes = range(len(name_parts), 0, -1)
    else:
        idxes = range(1, len(name_parts)+1)
    result = ['.'.join(name_parts[:i]) or '.' for i in idxes]
    return result


_name_re               = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*$")
_dotted_name_re        = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*([.][a-zA-Z_][a-zA-Z0-9_]*)*$")
_dotted_name_prefix_re = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]*([.][a-zA-Z_][a-zA-Z0-9_]*)*[.]?$")


def is_identifier(s, dotted=False, prefix=False):
    """
    Return whether ``s`` is a valid Python identifier name.

      >>> is_identifier("foo")
      True

      >>> is_identifier("foo+bar")
      False

      >>> is_identifier("from")
      False

    By default, we check whether ``s`` is a single valid identifier, meaning
    dots are not allowed.  If ``dotted=True``, then we check each dotted
    component::

      >>> is_identifier("foo.bar")
      False

      >>> is_identifier("foo.bar", dotted=True)
      True

      >>> is_identifier("foo..bar", dotted=True)
      False

      >>> is_identifier("foo.from", dotted=True)
      False

    By default, the string must comprise a valid identifier.  If
    ``prefix=True``, then allow strings that are prefixes of valid identifiers.
    Prefix=False excludes the empty string, strings with a trailing dot, and
    strings with a trailing keyword component, but prefix=True does not
    exclude these.

      >>> is_identifier("foo.bar.", dotted=True)
      False

      >>> is_identifier("foo.bar.", dotted=True, prefix=True)
      True

      >>> is_identifier("foo.or", dotted=True)
      False

      >>> is_identifier("foo.or", dotted=True, prefix=True)
      True

    :type s:
      ``str``
    :param dotted:
      If ``False`` (default), then the input must be a single name such as
      "foo".  If ``True``, then the input can be a single name or a dotted name
      such as "foo.bar.baz".
    :param prefix:
      If ``False`` (Default), then the input must be a valid identifier.  If
      ``True``, then the input can be a valid identifier or the prefix of a
      valid identifier.
    :rtype:
      ``bool``
    """
    if not isinstance(s, six.string_types):
        raise TypeError("is_identifier(): expected a string; got a %s"
                        % (type(s).__name__,))
    if six.PY3:
        if prefix:
            return is_identifier(s + '_', dotted=dotted, prefix=False)
        if dotted:
            return all(is_identifier(w, dotted=False) for w in s.split('.'))
        return s.isidentifier() and not _my_iskeyword(s)

    if prefix:
        if not s:
            return True
        if dotted:
            return bool(
                _dotted_name_prefix_re.match(s) and
                not any(_my_iskeyword(w) for w in s.split(".")[:-1]))
        else:
            return bool(_name_re.match(s))
    else:
        if dotted:
            # Use a regular expression that works for dotted names.  (As an
            # alternate implementation, one could imagine calling
            # all(is_identifier(w) for w in s.split(".")).  We don't do that
            # because s could be a long text string.)
            return bool(
                _dotted_name_re.match(s) and
                not any(_my_iskeyword(w) for w in s.split(".")))
        else:
            return bool(_name_re.match(s) and not _my_iskeyword(s))


def brace_identifiers(text):
    """
    Parse a string and yield all tokens of the form "{some_token}".

      >>> list(brace_identifiers("{salutation}, {your_name}."))
      ['salutation', 'your_name']
    """
    if isinstance(text, bytes):
        text = text.decode('utf-8', errors='replace')
    for match in re.finditer("{([a-zA-Z_][a-zA-Z0-9_]*)}", text):
        yield match.group(1)


class BadDottedIdentifierError(ValueError):
    pass


# TODO: Use in various places, esp where e.g. dotted_prefixes is used.
@total_ordering
class DottedIdentifier(object):
    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, six.string_types):
            return cls._from_name(arg)
        if isinstance(arg, (tuple, list)):
            return cls._from_name(".".join(arg))
        raise TypeError("DottedIdentifier: unexpected %s"
                        % (type(arg).__name__,))

    @classmethod
    def _from_name(cls, name):
        self = object.__new__(cls)
        self.name = str(name)
        if not is_identifier(self.name, dotted=True):
            if len(self.name) > 20:
                raise BadDottedIdentifierError("Invalid python symbol name")
            else:
                raise BadDottedIdentifierError("Invalid python symbol name %r"
                                               % (name,))
        self.parts = tuple(self.name.split('.'))
        return self

    @cached_attribute
    def parent(self):
        if len(self.parts) > 1:
            return DottedIdentifier('.'.join(self.parts[:-1]))
        else:
            return None

    @cached_attribute
    def prefixes(self):
        parts = self.parts
        idxes = range(1, len(parts)+1)
        result = ['.'.join(parts[:i]) for i in idxes]
        return tuple(DottedIdentifier(x) for x in result)

    def startswith(self, o):
        o = type(self)(o)
        return self.parts[:len(o.parts)] == o.parts

    def __getitem__(self, x):
        return type(self)(self.parts[x])

    def __len__(self):
        return len(self.parts)

    def __iter__(self):
        return (type(self)(x) for x in self.parts)

    def __add__(self, suffix):
        return type(self)("%s.%s") % (self, suffix)

    def __str__(self):
        return self.name

    def __repr__(self):
        return "%s(%r)" % (type(self).__name__, self.name)

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, DottedIdentifier):
            return NotImplemented
        return self.name == other.name

    def __ne__(self, other):
        if self is other:
            return False
        if not isinstance(other, DottedIdentifier):
            return NotImplemented
        return self.name != other.name

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, DottedIdentifier):
            return NotImplemented
        return self.name < other.name

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, DottedIdentifier):
            return NotImplemented
        return cmp(self.name, other.name)
