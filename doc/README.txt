

The PYFLYBY_PATH environment variable is used to determine which library files
to read.  This is a colon-separate list of filenames or directory names.
Earlier entries take precedence in case of conflicting imports.  The default
path is ~/.pyflyby/import_library, $PYFLYBY_DIR/share/pyflyby/import_library.
Use '-' in $PYFLYBY_PATH to include the default.

Example:
  PYFLYBY_PATH=~/myproject/myimports.py:-

