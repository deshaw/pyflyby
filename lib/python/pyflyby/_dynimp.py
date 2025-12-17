"""
Virtual module to create dynamic import at runtime.

It is sometime desirable to have auto import which are define only during
a session and never exist on a on-disk file.

This is injects a Dict module loader as well as a dictionary registry of in
memory module.

This is mostly use in IPython for lazy variable initialisation without having
to use proxy objects.

To use, put the following in your IPython startup files
(``~/.ipython/profile_default/startup/autoimp.py`), or in your IPython
configuration file:


.. code:: python

    from pyflyby._dynimp import add_import

    add_import("foo", "foo = 1")

    add_import(
        "df, data",
        '''
        import pandas as pd
        data = [1,2,3]
        df =  pd.DataFrame(data)
    ''',
    )

Now at the IPython prompt, if the pyflyby extension is loaded (either because
you started  using the ``py`` cli, or some configuration options like  ``ipython
--TerminalIPythonApp.extra_extensions=pyflyby``. When trying to use an undefined
variable like ``foo``, ``df`` or ``data``, the corresponding module will be
executed and the relevant variable imported.


"""
import importlib.abc
import importlib.util
import sys

from   textwrap                 import dedent
from   typing                   import FrozenSet

from   pyflyby._importclns      import Import, ImportSet

module_dict = {}

PYFLYBY_LAZY_LOAD_PREFIX = "from pyflyby_autoimport_"

def add_import(names: str, code: str, *, strict: bool = True):
    """
    Add a runtime generated import module

    Parameters
    ----------
    names: str
        name, or comma separated list variable names that should be created by
        executing and importing `code`.
    code: str
        potentially multiline string that will be turned into a module,
        executed and from which variables listed in names can be imported.
    strict: bool
        Raise in case of problem loading IPython of if pyflyby extension not installed.
        otherwise just ignore error



    Examples
    --------

    >>> add_import('pd, df', '''
    ...     import pandas a pd
    ...
    ...     df = pd.DataFrame([[1,2], [3,4]])
    ... ''', strict=False)  # don't fail doctest

    """
    try:
        ip = _raise_if_problem()
    except Exception:
        if strict:
            raise
        else:
            return
    return _add_import(ip, names, code)


def _raise_if_problem():
    try:
        import IPython
    except ModuleNotFoundError as e:
        raise ImportError("Dynamic autoimport requires IPython to be installed") from e

    ip = IPython.get_ipython()
    if ip is None:
        raise ImportError("Dynamic autoimport only work from within IPython")

    if not hasattr(ip, "_auto_importer"):
        raise ValueError(
            "IPython needs to be loaded with pyflyby extension for lazy variable to work"
        )
    return ip


def _add_import(ip, names: str, code: str) -> None:
    """
    private version of add_import
    """
    assert ip is not None
    module = PYFLYBY_LAZY_LOAD_PREFIX.split()[1]
    mang = module + names.replace(",", "_").replace(" ", "_")
    a: FrozenSet[Import] = ImportSet(f"from {mang} import {names}")._importset
    b: FrozenSet[Import] = ip._auto_importer.db.known_imports._importset
    s_import: FrozenSet[Import] = a | b

    ip._auto_importer.db.known_imports = ImportSet._from_imports(list(s_import))
    module_dict[mang] = dedent(code)

class DictLoader(importlib.abc.Loader):
    """
    A dict based loader for in-memory module definition.
    """
    def __init__(self, module_name, module_code):
        self.module_name = module_name
        self.module_code = module_code

    def create_module(self, spec):
        return None  # Use default module creation semantics

    def exec_module(self, module):
        """
        we exec module code directly in memory
        """
        exec(self.module_code, module.__dict__)


class DictFinder(importlib.abc.MetaPathFinder):
    """
    A meta path finder for abode DictLoader
    """
    def find_spec(self, fullname, path, target=None):
        if fullname in module_dict:
            module_code = module_dict[fullname]
            loader = DictLoader(fullname, module_code)
            return importlib.util.spec_from_loader(fullname, loader)
        return None


def inject():
    sys.meta_path.insert(0, DictFinder())
