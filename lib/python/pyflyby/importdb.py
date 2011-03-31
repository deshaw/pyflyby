
from __future__ import absolute_import, division, with_statement

import os

from pyflyby.file       import Filename
from pyflyby.importstmt import Imports

DEFAULT_PATH = [
    Filename(os.path.expanduser("~/.pyflyby/import_library")),
    Filename(__file__).real.dir.dir.dir.dir / "share/pyflyby/import_library"]

def library_files():
    path = filter(None, os.environ.get('PYFLYBY_PATH', '').split(':'))
    if path:
        # Replace '-' with DEFAULT_PATH
        try:
            idx = path.index('-')
        except ValueError:
            pass
        else:
            path[idx:idx+1] = DEFAULT_PATH
    else:
        path = DEFAULT_PATH
    path = [Filename(fn) for fn in path]
    if not path:
        raise Exception(
            "No import libraries found (PYFLYBY_PATH=%r, default=%r)"
            % (os.environ.get('PYFLYBY_PATH'), DEFAULT_PATH))
    files = [filename
             for fn in path
             for filename in fn.recursive_iterate()
             if filename.ext == '.py']
    return files


single_global_importdb = None
def global_importdb():
    global single_global_importdb
    if single_global_importdb is None:
        single_global_importdb = Imports(library_files()).by_import_as
    return single_global_importdb

