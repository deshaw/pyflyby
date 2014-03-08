Pyflyby is a set of tools that makes Python programming easier.

For editing python source code:
  * find-imports prints out how to import a particular symbol.
  * reformat-imports reformats the 'import' blocks.
  * tidy-imports adds missing 'import's, removes unused 'import's, and also
    reformats 'import' blocks.
  * collect-imports prints out all the imports in a given set of files.

For IPython interaction:
  * autoimport automatically imports symbols when needed.

Import Libraries
================

Quick start:
  To add known imports, edit ~/.pyflyby/known_imports/my_import_lib.py
  To add exclusions, edit ~/.pyflyby/known_imports/__remove__.py

Detailed answer:

Pyflyby uses "import libraries" that tell how to import a given symbol.

An import library file is simply a .py source file containing 'import' (or
'from ... import ...') lines.  These can be generated automatically with
collect-imports.

Known imports
-------------

Find-imports, tidy-imports, and autoimport consult the "known_imports"
database to figure out where to get an import.  For example, if the
known_imports database contains::
    from numpy import arange, NaN
then when you type the following in IPython::
    print arange(10)
the autoimporter would automatically execute "from numpy import arange".

The known_imports database comprises multiple files.  This makes it easy to
have project-specific known_imports along with global and per-user defaults.

The PYFLYBY_KNOWN_IMPORTS_PATH environment variable tells which files to read.
This is a colon-separated list of filenames or directory names.  The default
is:
  PYFLYBY_KNOWN_IMPORTS_PATH=~/.pyflyby/known_imports:$PYFLYBY_DIR/share/pyflyby/known_imports

If you set
  PYFLYBY_KNOWN_IMPORTS_PATH=/foo1/bar1:/foo2/bar2
then this replaces the default.
If you set
  PYFLYBY_KNOWN_IMPORTS_PATH=/foo1/bar1:/foo2/bar2:-
then this adds to the default.

$PYFLYBY_KNOWN_IMPORTS_PATH is searched recursively.  Filenames or
subdirectories beginning with '.' are ignored.


Exclusions
----------

As a special case, files named __remove__.py contain imports to *remove* from
the import library.  This is useful if you want to use a set of imports
maintained by someone else except for a few particular imports.


Mandatory imports
-----------------

The PYFLYBY_MANDATORY_IMPORTS_PATH environment variable lists directories
containing imports that tidy-imports adds to every file (unless
--no-add-mandatory).  This will generally contain __future__ imports that one
wishes to standardize across a codebase.


Emacs support
=============

* To get a `M-x tidy-imports' command in GNU Emacs, add to your ~/.emacs:

    (load "/path/to/pyflyby/lib/emacs/pyflyby.el")


- Pyflyby.el doesn't yet work with XEmacs; patches welcome.


Authorship
==========

Pyflyby is written by Karl Chen <Karl.Chen@quarl.org>
