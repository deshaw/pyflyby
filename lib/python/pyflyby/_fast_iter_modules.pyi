"""Stub file for _fast_iter_modules compiled extension module.

This module provides a fast implementation of pkgutil._iter_file_finder_modules
using C++ with pybind11.
"""

from __future__ import print_function

import importlib.machinery
from   typing                   import Generator, List

def _iter_file_finder_modules(
    importer: importlib.machinery.FileFinder,
    suffixes: List[str]
) -> Generator[tuple[str, bool], None, None]:
    """Iterate over modules in a file finder path.

    Parameters
    ----------
    importer : importlib.machinery.FileFinder
        The file finder to iterate modules from.
    suffixes : List[str]
        List of valid module suffixes (e.g., ['.py', '.pyd', '.so']).

    Yields
    ------
    tuple[str, bool]
        Tuples of (module_name, is_package).
    """
    ...
