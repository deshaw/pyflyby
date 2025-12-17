"""
This module contain utility functions to sort imports in a Python Block.
"""
from __future__ import annotations

from   collections              import Counter
from   dataclasses              import dataclass
from   itertools                import groupby
from   pyflyby._importstmt      import ImportStatement, PythonStatement
from   pyflyby._parse           import PythonBlock
from   typing                   import List, Tuple, Union


# @dataclass
# class ImportSection:
#     """
#     This represent an Import
#     """
#     sections: List[ImportGroup]


@dataclass
class ImportGroup:
    """
    Typically at the top of a file, the first import will be part
    of an ImportGroup, and subsequent imports
    will be other import groups which.

    Import sorting will affect only the imports in the same group,
    as we want import sorting to be indempotent. If import sorting
    were migrating imports between groups, then imports could be
    moved to sections were comments would nto be relevant.
    """

    imports: List[ImportStatement]

    @classmethod
    def from_statements(cls, statements: List[PythonStatement]) -> ImportGroup:
        return ImportGroup([ImportStatement(s) for s in statements])

    def sorted(self) -> ImportGroup:
        """
        return an ImportGroup with import sorted lexicographically.
        """
        return ImportGroup(sorted(self.imports, key=lambda x: x._cmp()))

    def sorted_subgroups(self) -> List[Tuple[bool, List[ImportStatement]]]:
        """
        Return a list of subgroup keyed by module and whether they are the sole import
        from this module.

        From issue #13, we will want to sort import from the same package together when
        there is more than one import and separat with a blank line

        We also group all imports from a package that appear only once together.

        For this we need both to know if the import is from a single import (the boolean).

        Returns
        -------
        bool:
           wether from a single import
        List[ImportStatement]
           The actual import.
        """
        c = Counter(imp.module[0] for imp in self.imports)
        return [
            (c[k] > 1, list(v)) for k, v in groupby(self.imports, lambda x: x.module[0])
        ]


def split_import_groups(
    statements: Tuple[PythonStatement],
) -> List[Union[ImportGroup, PythonStatement]]:
    """
    Given a list of statements split into import groups.

    One of the question is how to treat split with comments.

     - Do blank lines after groups with comments start a new block
     - Does the comment line create a complete new block.

    In particular because we want this to be indempotent,
    we can't move imports between groups.
    """

    # these are the import groups we'll
    groups: List[PythonStatement | ImportGroup] = []

    current_group: List[PythonStatement] = []
    statemt_iterator = iter(statements)
    for statement in statemt_iterator:
        if statement.is_blank and current_group:
            pass
            # currently do nothing with whitespace while in import groups.
        elif statement.is_import:
            # push on top of current_comment.
            current_group.append(statement)
        else:
            if current_group:
                groups.append(ImportGroup.from_statements(current_group))
            current_group = []
            groups.append(statement)

            # we should break of and populate rest
            # We can't do anything if we encounter any non-import statement,
            # as we do no know if it can be a conditional.
            # technically I guess we coudl find another import block, and reorder these.
    if current_group:
        groups.append(ImportGroup.from_statements(current_group))

    # this is an iterator, not an iterable, we exaust it to reify the rest.

    # first group may be empty if the first line is a comment.
    # We filter and sort relevant statements.
    groups = [g for g in groups if groups]
    sorted_groups: List[PythonStatement | ImportGroup] = [
        g.sorted() if isinstance(g, ImportGroup) else g for g in groups
    ]
    return sorted_groups


def regroup(groups: List[ImportGroup | PythonStatement]) -> PythonBlock:
    """
    given import groups and list of statement, return an Python block with sorted import
    """
    res: str = ""
    in_single = False
    for group in groups:
        if isinstance(group, ImportGroup):
            # the subgroup here will be responsible for  groups reordering.
            for mult, subgroup in group.sorted_subgroups():
                if mult:
                    if in_single:
                        res += "\n"
                    if not res.endswith("\n"):
                        res += "\n"
                    for x in subgroup:
                        res += x.pretty_print(import_column=30).rstrip() + "\n"
                    if not res.endswith("\n\n"):
                        res += "\n"
                    in_single = False
                else:
                    assert len(subgroup) == 1
                    in_single = True
                    for sub in subgroup:
                        res += str(sub).rstrip() + "\n"

            if not res.endswith("\n\n"):
                res += "\n"
        else:
            if in_single and not res.endswith("\n\n"):
                res += "\n"
            in_single = False
            res += str(PythonBlock(group))

    return PythonBlock.concatenate([PythonBlock(res)])


def sort_imports(block: PythonBlock) -> PythonBlock:
    assert isinstance(block, PythonBlock)
    # we ignore below that block.statement can be a List[Unknown]
    gs = split_import_groups(block.statements)  # type: ignore
    # TODO: math the other fileds like filename....
    return regroup(gs)
