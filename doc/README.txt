PyFlyBy is a set of tools for automatically editing python source files.

- find-imports prints out how to import a particular symbol.
- reformat-imports reformats the 'import' blocks.
- tidy-imports adds missing 'import's, removes unused 'import's, and also
  reformats 'import' blocks.
- collect-imports prints out all the imports in a given set of files.

Find-imports and tidy-imports use "import libraries" to know how to import a
given symbol.  An import library file is simply a .py source file containing
'import' (or 'from ... import ...') lines.  These can be generated
automatically with collect-imports.

The PYFLYBY_PATH environment variable is used to determine which library files
to read.  This is a colon-separate list of filenames or directory names.
Earlier entries take precedence in case of conflicting imports.  The default
path is ~/.pyflyby/import_library, $PYFLYBY_DIR/share/pyflyby/import_library.
Use '-' in $PYFLYBY_PATH to include the default.

Example:
  PYFLYBY_PATH=~/myproject/myimports.py:-

