
from __future__ import absolute_import, division, with_statement

import os

from   pyflyby.file             import Filename
from   pyflyby.importstmt       import Imports
from   pyflyby.util             import memoize


DEFAULT_CONFIG_DIRS = [
    Filename(os.path.expanduser("~/.pyflyby")),
    Filename(__file__).real.dir.dir.dir.dir / "share/pyflyby",
    ]

def recursive_python_files(pathnames):
    return [filename
            for pathname in pathnames
            for filename in pathname.recursive_iterate()
            if filename.ext == '.py']


def get_python_path(env_var_name, default_path, recurse=False):
    '''
    @rtype:
      C{tuple} of C{Filename}s
    '''
    path = filter(None, os.environ.get(env_var_name, '').split(':'))
    if path:
        # Replace '-' with DEFAULT_PATH
        try:
            idx = path.index('-')
        except ValueError:
            pass
        else:
            path[idx:idx+1] = default_path
    else:
        path = default_path
    path = [Filename(fn) for fn in path]
    if recurse:
        path = recursive_python_files(path)
    if not path:
        raise Exception(
            "No import libraries found (%s=%r, default=%r)"
            % (env_var_name, os.environ.get(env_var_name), default_path))
    return tuple(path)


global_config_dirs = get_python_path('PYFLYBY_PATH', DEFAULT_CONFIG_DIRS)

def get_import_library(env_var_name, subdir_name):
    return Imports(
        get_python_path(
            env_var_name,
            [d/subdir_name for d in global_config_dirs],
            recurse=True))


@memoize
def global_known_imports():
    return get_import_library('PYFLYBY_KNOWN_IMPORTS_PATH', 'known_imports')


def global_mandatory_imports():
    return get_import_library(
        'PYFLYBY_MANDATORY_IMPORTS_PATH', 'mandatory_imports')
