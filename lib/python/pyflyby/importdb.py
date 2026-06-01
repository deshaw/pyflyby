# pyflyby/importdb.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

# Deprecated stub for backwards compatibility.

from __future__ import annotations, print_function

import warnings

from   pyflyby._importclns      import ImportSet
from   pyflyby._importdb        import ImportDB


def global_known_imports() -> ImportSet:
    # Deprecated stub for backwards compatibility.
    warnings.warn(
        "global_known_imports() has been deprecated since 2014-10; "
        "use ImportDB.get_default('.').known_imports instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ImportDB.get_default(".").known_imports


def global_mandatory_imports() -> ImportSet:
    # Deprecated stub for backwards compatibility.
    warnings.warn(
        "global_mandatory_imports() has been deprecated since 2014-10; "
        "use ImportDB.get_default('.').mandatory_imports instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return ImportDB.get_default(".").mandatory_imports
