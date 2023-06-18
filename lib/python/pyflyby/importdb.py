# pyflyby/importdb.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

# Deprecated stub for backwards compatibility.



from   pyflyby._importdb        import ImportDB


def global_known_imports():
    # Deprecated stub for backwards compatibility.
    return ImportDB.get_default(".").known_imports


def global_mandatory_imports():
    # Deprecated stub for backwards compatibility.
    return ImportDB.get_default(".").mandatory_imports
