# pyflyby/_importclns.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

from __future__ import annotations

import sys

from   collections              import defaultdict
from   functools                import total_ordering

from   pyflyby._flags           import CompilerFlags
from   pyflyby._idents          import dotted_prefixes, is_identifier
from   pyflyby._importstmt      import (Import, ImportFormatParams,
                                        ImportStatement,
                                        NonImportStatementError)
from   pyflyby._parse           import PythonBlock
from   pyflyby._util            import (cached_attribute, cmp, partition,
                                        stable_unique)

from   typing                   import (ClassVar, Dict, FrozenSet, Sequence,
                                        Union)

if sys.version_info < (3, 12):
    from typing_extensions          import Self
else:
    from typing import Self


class NoSuchImportError(ValueError):
    pass


class ConflictingImportsError(ValueError):
    pass

@total_ordering
class ImportSet:
    r"""
    Representation of a set of imports organized into import statements.

      >>> ImportSet('''
      ...     from m1 import f1
      ...     from m2 import f1
      ...     from m1 import f2
      ...     import m3.m4 as m34
      ... ''')
      ImportSet('''
        from m1 import f1, f2
        from m2 import f1
        from m3 import m4 as m34
      ''')

    An ``ImportSet`` is an immutable data structure.
    """

    _EMPTY: ClassVar[ImportSet]
    _importset: FrozenSet[Import]

    def __new__(cls, arg, ignore_nonimports=False, ignore_shadowed=False):
        """
        Return as an `ImportSet`.

        :param ignore_nonimports:
          If ``False``, complain about non-imports.  If ``True``, ignore
          non-imports.
        :param ignore_shadowed:
          Whether to ignore shadowed imports.  If ``False``, then keep all
          unique imports, even if they shadow each other.  Note that an
          ``ImportSet`` is unordered; an ``ImportSet`` with conflicts will only
          be useful for very specific cases (e.g. set of imports to forget
          from known-imports database), and not useful for outputting as code.
          If ``ignore_shadowed`` is ``True``, then earlier shadowed imports are
          ignored.
        :rtype:
          `ImportSet`
        """
        if isinstance(arg, cls):
            if ignore_shadowed:
                return cls._from_imports(list(arg._importset), ignore_shadowed=True)
            else:
                return arg
        return cls._from_args(
            arg,
            ignore_nonimports=ignore_nonimports,
            ignore_shadowed=ignore_shadowed)

    def __or__(self: Self, other: Self) -> Self:
        return type(self)._from_imports(list(self._importset | other._importset))

    @classmethod
    def _from_imports(cls, imports: Sequence[Import], ignore_shadowed: bool = False):
        """
        :type imports:
          Sequence of `Import` s
        :param ignore_shadowed:
          See `ImportSet.__new__`.
        :rtype:
          `ImportSet`
        """
        # Canonicalize inputs.
        by_import_as: Dict[Union[str, Import], Import]
        filtered_imports: Sequence[Import]
        for imp in imports:
            assert isinstance(imp, Import)
        _imports = [Import(imp) for imp in imports]
        if ignore_shadowed:
            # Filter by overshadowed imports.  Later imports take precedence.
            by_import_as = {}
            for imp in _imports:
                if imp.import_as == "*":
                    # Keep all unique star imports.
                    by_import_as[imp] = imp
                else:
                    by_import_as[imp.import_as] = imp
            filtered_imports = list(by_import_as.values())
        else:
            filtered_imports = _imports
        # Construct and return.
        self = object.__new__(cls)
        self._importset = frozenset(filtered_imports)
        return self

    @classmethod
    def _from_args(cls, args, ignore_nonimports:bool=False, ignore_shadowed=False) -> Self:
        """
        :type args:
          ``tuple`` or ``list`` of `ImportStatement` s, `PythonStatement` s,
          `PythonBlock` s, `FileText`, and/or `Filename` s
        :param ignore_nonimports:
          If ``False``, complain about non-imports.  If ``True``, ignore
          non-imports.
        :param ignore_shadowed:
          See `ImportSet.__new__`.
        :rtype:
          `ImportSet`
        """
        if not isinstance(args, (tuple, list)):
            args = [args]
        # Filter empty arguments to allow the subsequent optimizations to work
        # more often.
        args = [a for a in args if a]
        if not args:
            return cls._EMPTY  # type: ignore[return-value]
        # If we only got one ``ImportSet``, just return it.
        if len(args) == 1 and type(args[0]) is cls and not ignore_shadowed:
            return args[0]
        # Collect all `Import` s from arguments.
        imports = []
        for arg in args:
            if isinstance(arg, Import):
                imports.append(arg)
            elif isinstance(arg, ImportSet):
                imports.extend(arg.imports)
            elif isinstance(arg, ImportStatement):
                imports.extend(arg.imports)
            elif isinstance(arg, str) and is_identifier(arg, dotted=True):
                imports.append(Import(arg))
            else: # PythonBlock, PythonStatement, Filename, FileText, str
                if not isinstance(arg, PythonBlock):
                    block = PythonBlock(arg)
                else:
                    block = arg
                for statement in block.statements:
                    # Ignore comments/blanks.
                    if statement.is_comment_or_blank:
                        pass
                    elif statement.is_import:
                        imports.extend(ImportStatement(statement).imports)
                    elif ignore_nonimports:
                        pass
                    else:
                        raise NonImportStatementError(
                            "Got non-import statement %r" % (statement,))
        return cls._from_imports(imports, ignore_shadowed=ignore_shadowed)

    def with_imports(self, other):
        """
        Return a new `ImportSet` that is the union of ``self`` and
        ``new_imports``.

          >>> impset = ImportSet('from m import t1, t2, t3')
          >>> impset.with_imports('import m.t2a as t2b')
          ImportSet('''
            from m import t1, t2, t2a as t2b, t3
          ''')

        :type other:
          `ImportSet` (or convertible)
        :rtype:
          `ImportSet`
        """
        other = ImportSet(other)
        return type(self)._from_imports(list(self._importset | other._importset))

    def without_imports(self, removals):
        """
        Return a copy of self without the given imports.

          >>> imports = ImportSet('from m import t1, t2, t3, t4')
          >>> imports.without_imports(['from m import t3'])
          ImportSet('''
            from m import t1, t2, t4
          ''')

        :type removals:
          `ImportSet` (or convertible)
        :rtype:
          `ImportSet`
        """
        removals = ImportSet(removals)
        if not removals:
            return self # Optimization
        # Preprocess star imports to remove.
        star_module_removals = set(
            [imp.split.module_name
             for imp in removals if imp.split.member_name == "*"])
        # Filter imports.
        new_imports = []
        for imp in self:
            if imp in removals:
                continue
            if star_module_removals and imp.split.module_name:
                prefixes = dotted_prefixes(imp.split.module_name)
                if any(pfx in star_module_removals for pfx in prefixes):
                    continue
            new_imports.append(imp)
        # Return.
        if len(new_imports) == len(self):
            return self # Space optimization
        return type(self)._from_imports(new_imports)

    @cached_attribute
    def _by_module_name(self):
        """
        :return:
          (mapping from name to __future__ imports,
          mapping from name to non-'from' imports,
          mapping from name to 'from' imports)
        """
        ftr_imports = defaultdict(set)
        pkg_imports = defaultdict(set)
        frm_imports = defaultdict(set)
        for imp in self._importset:
            module_name, member_name, import_as = imp.split
            if module_name is None:
                pkg_imports[member_name].add(imp)
            elif module_name == '__future__':
                ftr_imports[module_name].add(imp)
            else:
                frm_imports[module_name].add(imp)
        return tuple(
            dict((k, frozenset(v)) for k, v in imports.items())
            for imports in [ftr_imports, pkg_imports, frm_imports]
        )

    def get_statements(self, separate_from_imports=True):
        """
        Canonicalized `ImportStatement` s.
        These have been merged by module and sorted.

          >>> importset = ImportSet('''
          ...     import a, b as B, c, d.dd as DD
          ...     from __future__ import division
          ...     from _hello import there
          ...     from _hello import *
          ...     from _hello import world
          ... ''')

          >>> for s in importset.get_statements(): print(s)
          from __future__ import division
          import a
          import b as B
          import c
          from _hello import *
          from _hello import there, world
          from d import dd as DD

        :rtype:
          ``tuple`` of `ImportStatement` s
        """
        groups = self._by_module_name
        if not separate_from_imports:
            def union_dicts(*dicts):
                result = {}
                for label, dct in enumerate(dicts):
                    for k, v in dct.items():
                        result[(k, label)] = v
                return result
            groups = [groups[0], union_dicts(*groups[1:])]
        result = []
        for importgroup in groups:
            for _, imports in sorted(importgroup.items()):
                star_imports, nonstar_imports = (
                    partition(imports, lambda imp: imp.import_as == "*"))
                assert len(star_imports) <= 1
                if star_imports:
                    result.append(ImportStatement(star_imports))
                if nonstar_imports:
                    result.append(ImportStatement(sorted(nonstar_imports)))
        return tuple(result)

    @cached_attribute
    def statements(self):
        """
        Canonicalized `ImportStatement` s.
        These have been merged by module and sorted.

        :rtype:
          ``tuple`` of `ImportStatement` s
        """
        return self.get_statements(separate_from_imports=True)

    @cached_attribute
    def imports(self):
        """
        Canonicalized imports, in the same order as ``self.statements``.

        :rtype:
          ``tuple`` of `Import` s
        """
        return tuple(
            imp
            for importgroup in self._by_module_name
            for _, imports in sorted(importgroup.items())
            for imp in sorted(imports))

    @cached_attribute
    def by_import_as(self):
        """
        Map from ``import_as`` to `Import`.

          >>> ImportSet('from aa.bb import cc as dd').by_import_as
          {'dd': (Import('from aa.bb import cc as dd'),)}

        :rtype:
          ``dict`` mapping from ``str`` to tuple of `Import` s
        """
        d = defaultdict(list)
        for imp in self._importset:
            d[imp.import_as].append(imp)
        return dict((k, tuple(sorted(stable_unique(v)))) for k, v in d.items())

    @cached_attribute
    def member_names(self):
        r"""
        Map from parent module/package ``fullname`` to known member names.

          >>> impset = ImportSet("import numpy.linalg.info\nfrom sys import exit as EXIT")
          >>> import pprint
          >>> pprint.pprint(impset.member_names)
          {'': ('EXIT', 'numpy', 'sys'),
           'numpy': ('linalg',),
           'numpy.linalg': ('info',),
           'sys': ('exit',)}

        This is used by the autoimporter module for implementing tab completion.

        :rtype:
          ``dict`` mapping from ``str`` to tuple of ``str``
        """
        d = defaultdict(set)
        for imp in self._importset:
            if '.' not in imp.import_as:
                d[""].add(imp.import_as)
            prefixes = dotted_prefixes(imp.fullname)
            d[""].add(prefixes[0])
            for prefix in prefixes[1:]:
                splt = prefix.rsplit(".", 1)
                d[splt[0]].add(splt[1])
        return dict((k, tuple(sorted(v))) for k, v in d.items())

    @cached_attribute
    def conflicting_imports(self):
        r"""
        Returns imports that conflict with each other.

          >>> ImportSet('import b\nfrom f import a as b\n').conflicting_imports
          ('b',)

          >>> ImportSet('import b\nfrom f import a\n').conflicting_imports
          ()

        :rtype:
          ``bool``
        """
        return tuple(k for k, v in self.by_import_as.items() if len(v) > 1 and k != "*")

    @cached_attribute
    def flags(self):
        """
        If this contains __future__ imports, then the bitwise-ORed of the
        compiler_flag values associated with the features.  Otherwise, 0.
        """
        imports = self._by_module_name[0].get("__future__", [])
        return CompilerFlags(*[imp.flags for imp in imports])

    def __repr__(self):
        printed = self.pretty_print(allow_conflicts=True)
        lines = "".join("  "+line for line in printed.splitlines(True))
        return "%s('''\n%s''')" % (type(self).__name__, lines)

    def pretty_print(self, params=None, allow_conflicts=False):
        """
        Pretty-print a block of import statements into a single string.

        :type params:
          `ImportFormatParams`
        :rtype:
          ``str``
        """
        params = ImportFormatParams(params)
        # TODO: instead of complaining about conflicts, just filter out the
        # shadowed imports at construction time.
        if not allow_conflicts and self.conflicting_imports:
            raise ConflictingImportsError(
                "Refusing to pretty-print because of conflicting imports: " +
                '; '.join(
                    "%r imported as %r" % (
                        [imp.fullname for imp in self.by_import_as[i]], i)
                    for i in self.conflicting_imports))
        from_spaces = max(1, params.from_spaces)
        def do_align(statement):
            return statement.fromname != '__future__' or params.align_future
        def pp(statement, import_column):
            if do_align(statement):
                return statement.pretty_print(
                    params=params, import_column=import_column,
                    from_spaces=from_spaces)
            else:
                return statement.pretty_print(
                    params=params, import_column=None, from_spaces=1)
        statements = self.get_statements(
            separate_from_imports=params.separate_from_imports)
        def isint(x): return isinstance(x, int) and not isinstance(x, bool)
        if not statements:
            import_column = None
        elif isinstance(params.align_imports, bool):
            if params.align_imports:
                fromimp_stmts = [
                    s for s in statements if s.fromname and do_align(s)]
                if fromimp_stmts:
                    import_column = (
                        max(len(s.fromname) for s in fromimp_stmts)
                        + from_spaces + 5)
                else:
                    import_column = None
            else:
                import_column = None
        elif isinstance(params.align_imports, int):
            import_column = params.align_imports
        elif isinstance(params.align_imports, (tuple, list, set)):
            # If given a set of candidate alignment columns, then try each
            # alignment column and pick the one that yields the fewest number
            # of output lines.
            if not all(isinstance(x, int) for x in params.align_imports):
                raise TypeError("expected set of integers; got %r"
                                % (params.align_imports,))
            candidates = sorted(set(params.align_imports))
            if len(candidates) == 0:
                raise ValueError("list of zero candidate alignment columns specified")
            elif len(candidates) == 1:
                # Optimization.
                import_column = next(iter(candidates))
            else:
                def argmin(map):
                    items = iter(sorted(map.items()))
                    min_k, min_v = next(items)
                    for k, v in items:
                        if v < min_v:
                            min_k = k
                            min_v = v
                    return min_k
                def count_lines(import_column):
                    return sum(
                        s.pretty_print(
                            params=params, import_column=import_column,
                            from_spaces=from_spaces).count("\n")
                        for s in statements)
                # Construct a map from alignment column to total number of
                # lines.
                col2length = dict((c, count_lines(c)) for c in candidates)
                # Pick the column that yields the fewest lines.  Break ties by
                # picking the smaller column.
                import_column = argmin(col2length)
        else:
            raise TypeError(
                "ImportSet.pretty_print(): unexpected params.align_imports type %s"
                % (type(params.align_imports).__name__,))
        return ''.join(pp(statement, import_column) for statement in statements)

    def __contains__(self, x) -> bool:
        return x in self._importset

    def __eq__(self, other) -> bool:
        if self is other:
            return True
        if not isinstance(other, ImportSet):
            return NotImplemented
        return self._importset == other._importset

    def __ne__(self, other) -> bool:
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, ImportSet):
            return NotImplemented
        return self._importset < other._importset

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, ImportSet):
            return NotImplemented
        return cmp(self._importset, other._importset)

    def __hash__(self):
        return hash(self._importset)

    def __len__(self) -> int:
        return len(self.imports)

    def __iter__(self):
        return iter(self.imports)


ImportSet._EMPTY = ImportSet._from_imports([])


@total_ordering
class ImportMap(object):
    r"""
    A map from import fullname identifier to fullname identifier.

      >>> ImportMap({'a.b': 'aa.bb', 'a.b.c': 'aa.bb.cc'})
      ImportMap({'a.b': 'aa.bb', 'a.b.c': 'aa.bb.cc'})

    An ``ImportMap`` is an immutable data structure.
    """

    _data: Dict
    _EMPTY : ClassVar[ImportSet]

    def __new__(cls, arg):
        if isinstance(arg, cls):
            return arg
        if isinstance(arg, (tuple, list)):
            return cls._merge(arg)
        if isinstance(arg, dict):
            if not len(arg):
                return cls._EMPTY
            return cls._from_map(arg)
        raise TypeError("ImportMap: expected a dict, not a %s" % (type(arg).__name__,))

    def __or__(self, other):
        assert isinstance(other, ImportMap)
        assert set(self._data.keys()).intersection(other._data.keys()) == set(), set(self._data.keys()).intersection(other._data.keys())
        return self._merge([self, other])

    @classmethod
    def _from_map(cls, arg):
        data = dict((Import(k).fullname, Import(v).fullname)
                    for k, v in arg.items())
        self = object.__new__(cls)
        self._data = data
        return self

    @classmethod
    def _merge(cls, maps):
        maps = [cls(m) for m in maps]
        maps = [m for m in maps if m]
        if not maps:
            return cls._EMPTY
        data = {}
        for map_ in maps:
            data.update(map_._data)
        return cls(data)

    def __getitem__(self, k):
        k = Import(k).fullname
        return self._data.__getitem__(k)

    def __iter__(self):
        return iter(self._data)

    def items(self):
        return self._data.items()

    def iteritems(self):
        return self._data.items()

    def iterkeys(self):
        return iter(self._data.keys())

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def __len__(self):
        return len(self._data)

    def without_imports(self, removals):
        """
        Return a copy of self without the given imports.
        Matches both keys and values.
        """
        removals = ImportSet(removals)
        if not removals:
            return self # Optimization
        cls = type(self)
        result = [(k, v) for k, v in self._data.items()
                  if Import(k) not in removals and Import(v) not in removals]
        if len(result) == len(self._data):
            return self # Space optimization
        return cls(dict(result))

    def __repr__(self):
        s = ", ".join("%r: %r" % (k,v) for k,v in sorted(self.items()))
        return "ImportMap({%s})" % s

    def __eq__(self, other):
        if self is other:
            return True
        if not isinstance(other, ImportMap):
            return NotImplemented
        return self._data == other._data

    def __ne__(self, other):
        return not (self == other)

    # The rest are defined by total_ordering
    def __lt__(self, other):
        if not isinstance(other, ImportMap):
            return NotImplemented
        return self._data < other._data

    def __cmp__(self, other):
        if self is other:
            return 0
        if not isinstance(other, ImportMap):
            return NotImplemented
        return cmp(self._data, other._data)

    def __hash__(self):
        h = hash(self._data)
        self.__hash__ = lambda: h
        return h


ImportMap._EMPTY = ImportMap._from_map({})
