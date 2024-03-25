# pyflyby/autoimport.py.
# Copyright (C) 2011, 2012, 2013, 2014 Karl Chen.
# License: MIT http://opensource.org/licenses/MIT

# Deprecated stub for backwards compatibility.
#
# Change your old code from:
#   import pyflyby.autoimport
#   pyflyby.autoimport.install_auto_importer()
# to:
#   import pyflyby
#   pyflyby.enable_auto_importer()



from   pyflyby._interactive     import enable_auto_importer

install_auto_importer = enable_auto_importer

__all__ = ['install_auto_importer']
