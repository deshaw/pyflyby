#########
 Pyflyby
#########

.. image:: https://badge.fury.io/py/pyflyby.svg
   :target: https://pypi.org/project/pyflyby/

.. image:: https://travis-ci.org/deshaw/pyflyby.png?branch=master
   :target: https://travis-ci.org/deshaw/pyflyby

Pyflyby is a set of Python programming productivity tools for Python.

For command-line interaction:
  * ``py``: command-line multitool

For IPython interaction:
  * ``autoimporter``: automatically imports symbols when needed.

For editing python source code:
  * ``tidy-imports``: adds missing 'import's, removes unused 'import's,
    and also reformats import blocks.
  * ``find-import``: prints to stdout how to import a particular symbol.
  * ``reformat-imports``: reformats ``import`` blocks
  * ``collect-imports``: prints out all the imports in a given set of files.
  * ``collect-exports``: prints out definitions in a given set of modules,
    in the form of import statements.
  * ``transform-imports``: renames imported modules/functions.

`Learn more about Pyflyby <https://www.deshaw.com/library/desco-quansight-improving-jupyter-efficiency>`_ in this blog post.

Installation
============

.. code:: bash

    $ pip install pyflyby

This creates an alias for your `ipython` named `py` which runs the `pyflyby` plug internally.
 `pyflyby` has a dependency on `ipython`, if it isn't already installed do install it with:

.. code:: bash

    $ pip install ipython


Quick start: Autoimporter + IPython
===================================

.. code:: bash

   $ py
   In [1]: re.search("[a-z]+", "....hello...").group(0)
   [PYFLYBY] import re
   Out[1]: 'hello'

   In [2]: chisqprob(arange(5), 2)
   [PYFLYBY] from numpy import arange
   [PYFLYBY] from scipy.stats import chisqprob
   Out[2]: [ 1.      0.6065  0.3679  0.2231  0.1353]

To load pyflyby into an existing IPython session as a 1-off:

.. code:: bash

   $ ipython
   In [1]: %load_ext pyflyby

To configure IPython/Jupyter Notebook to load pyflyby automatically:

.. code:: bash

   $ py pyflyby.install_in_ipython_config_file

or

.. code:: bash

   $ echo 'c.InteractiveShellApp.extensions.append("pyflyby")' \
     >> ~/.ipython/profile_default/ipython_config.py

   $ ipython
   In [1]: b64decode('aGVsbG8=')
   [PYFLYBY] from base64 import b64decode
   Out[1]: 'hello'

Auto importer lazy variables
----------------------------

It is possible to use the autoimporter to lazily define variables.

To use, put the following in your IPython startup files
(``~/.ipython/profile_default/startup/autoimp.py``), or in your IPython
configuration file:

.. code:: python


    from pyflyby import add_import

    add_import("foo", "foo = 1")

    add_import(
        "df, data as dd",
        '''
        import pandas as pd
        data = [1,2,3]
        df =  pd.DataFrame(data)
    ''')


You can add the keyword ``strict=False`` to not fail if not in IPython or of the
pyflyby extensions is not loaded.




Quick start: ``py`` command-line multi-tool
===========================================

.. code:: bash

  $ py b64decode aGVsbG8=
  [PYFLYBY] from base64 import b64decode
  [PYFLYBY] b64decode('aGVsbG8=', altchars=None)
  'hello'

  $ py log2 sys.maxint
  [PYFLYBY] from numpy import log2
  [PYFLYBY] import sys
  [PYFLYBY] log2(9223372036854775807)
  63.0

  $ py 'plot(cos(arange(30)))'
  [PYFLYBY] from numpy import arange
  [PYFLYBY] from numpy import cos
  [PYFLYBY] from matplotlib.pyplot import plot
  [PYFLYBY] plot(cos(arange(30)))
  <plot>

  $ py 38497631 / 13951446
  2.7594007818257693

  $ py foo.py

Quick start: ``tidy-imports``
=============================

To use ``tidy-imports``, just specify the filename(s) to tidy.

For example:

.. code::

   $ echo 're.search("[a-z]+", "....hello..."), chisqprob(arange(5), 2)' > foo.py

   $ tidy-imports foo.py
   --- /tmp/foo.py
   +++ /tmp/foo.py
   @@ -1 +1,9 @@
   +from __future__ import absolute_import, division, with_statement
   +
   +from   numpy                    import arange
   +from   scipy.stats              import chisqprob
   +import re
   +
    re.search("[a-z]+", "....hello..."), chisqprob(arange(5), 2)

   Replace /tmp/foo.py? [y/N]

To exclude a file, use `--exclude <pattern>`.

Quick start: import libraries
=============================

Create a file named .pyflyby with lines such as

.. code:: python

   from mypackage.mymodule import MyClass, my_function
   import anotherpackage.anothermodule

You can put this file in your home directory or in the same directory as your
``*.py`` files.


Details: automatic imports
==========================

AUTOMATIC IMPORTS - never type "import" again!

This module allows your "known imports" to work automatically in your IPython
interactive session without having to type the 'import' statements (and also
without having to slow down your Python startup with imports you only use
occasionally).

Example::

  In [1]: re.search("[a-z]+", "....hello...").group(0)
  [PYFLYBY] import re
  Out[1]: 'hello'

  In [2]: chisqprob(arange(5), 2)
  [PYFLYBY] from numpy import arange
  [PYFLYBY] from scipy.stats import chisqprob
  Out[2]: [ 1.      0.6065  0.3679  0.2231  0.1353]

  In [3]: np.sin(arandom(5))
  [PYFLYBY] from numpy.random import random as arandom
  [PYFLYBY] import numpy as np
  Out[3]: [ 0.0282  0.0603  0.4653  0.8371  0.3347]

  In [4]: isinstance(42, Number)
  [PYFLYBY] from numbers import Number
  Out[4]: True


It just works
-------------

Tab completion works, even on modules that are not yet imported.  In the
following example, notice that numpy is imported when we need to know its
members, and only then::

  $ ipython
  In [1]: nump<TAB>
  In [1]: numpy
  In [1]: numpy.arang<TAB>
  [PYFLYBY] import numpy
  In [1]: numpy.arange


The IPython "?" magic help (pinfo/pinfo2) automatically imports symbols first
if necessary::

  $ ipython
  In [1]: arange?
  [PYFLYBY] from numpy import arange
  ... Docstring: arange([start,] stop[, step,], dtype=None) ...

Other IPython magic commands work as well::

  $ ipython
  In [1]: %timeit np.cos(pi)
  [PYFLYBY] import numpy as np
  [PYFLYBY] from numpy import pi
  100000 loops, best of 3: 2.51 us per loop

  $ echo 'print arange(4)' > foo.py
  $ ipython
  In [1]: %run foo.py
  [PYFLYBY] from numpy import arange
  [0 1 2 3]

.. warning::

    Auto-import on ``Tab`` completion requires IPython 9.3 or newer.


Implementation details
----------------------

The automatic importing happens at parse time, before code is executed.  The
namespace never contains entries for names that are not yet imported.

This method of importing at parse time contrasts with previous implementations
of automatic importing that use proxy objects.  Those implementations using
proxy objects don't work as well, because it is impossible to make proxy
objects behave perfectly.  For example, ``instance(x, T)`` will return the wrong
answer if either x or T is a proxy object.


Details: import libraries
=========================

Pyflyby uses "import libraries" that tell how to import a given symbol.

An import library file is simply a python source file containing 'import' (or
'from ... import ...') lines.  These can be generated automatically with
``collect-imports`` and ``collect-exports``.

Known imports
-------------

Find-imports, ``tidy-imports``, and autoimport consult the database of known
imports to figure out where to get an import.  For example, if the
imports database contains::

    from numpy import arange, NaN

then when you type the following in IPython::

    print(arange(10))

the autoimporter would automatically execute ``from numpy import arange``.

The database can be one file or multiple files.  This makes it easy to have
project-specific known_imports along with global and per-user defaults.

The ``PYFLYBY_PATH`` environment variable specifies which files to read.
This is a colon-separated list of filenames or directory names.  The default
is::

  PYFLYBY_PATH=/etc/pyflyby:~/.pyflyby:.../.pyflyby

If you set::

  PYFLYBY_PATH=/foo1/bar1:/foo2/bar2

then this replaces the default.

You can use a hyphen to include the default in the path.  If you set::

  PYFLYBY_PATH=/foo1/bar1:-:/foo2/bar2

then this reads ``/foo1/bar1``, then the default locations, then ``/foo2/bar2``.

In ``$PYFLYBY_PATH``, ``.../.pyflyby`` (with _three_ dots) means that all ancestor
directories are searched for a member named ".pyflyby".

For example, suppose the following files exist::

  /etc/pyflyby/stuff.py
  /u/quarl/.pyflyby/blah1.py
  /u/quarl/.pyflyby/more/blah2.py
  /proj/share/mypythonstuff/.pyflyby
  /proj/share/mypythonstuff/foo/bar/.pyflyby/baz.py
  /.pyflyby

Further, suppose:

  * ``/proj`` is on a separate file system from ``/``.
  * ``$HOME=/u/quarl``

Then ``tidy-imports /proj/share/mypythonstuff/foo/bar/quux/zot.py`` will by
default use the following::

  /etc/pyflyby/stuff.py
  /u/quarl/.pyflyby/blah1.py
  /u/quarl/.pyflyby/more/blah2.py
  /proj/share/mypythonstuff/foo/bar/.pyflyby/baz.py
  /proj/share/mypythonstuff/.pyflyby (a file)

.. note::

  * ``/.pyflyby`` is not included, because traversal stops at file system
    boundaries, and in this example, ``/proj`` is on a different file system than
    ``/``.
  * ``.pyflyby`` (in ``$HOME`` or near the target file) can be a file or a directory.
    If it is a directory, then it is recursively searched for ``*.py`` files.
  * The order usually doesn't matter, but if there are "forget" instructions
    (see below), then the order matters.  In the default ``$PYFLYBY_PATH``,
    .../.pyflyby is placed last so that per-directory configuration can
    override per-user configuration, which can override systemwide
    configuration.


Forgetting imports
------------------

Occasionally you may have reason to tell pyflyby to "forget" entries from the
database of known imports.

You can put the following in any file reachable from ``$PYFLYBY_PATH``::

  __forget_imports__ = ["from numpy import NaN"]

This is useful if you want to use a set of imports maintained by someone else
except for a few particular imports.

Entries in ``$PYFLYBY_PATH`` are processed left-to-right in the order specified,
so put the files containing these at the end of your ``$PYFLYBY_PATH``.  By
default, ``tidy-imports`` and friends process ``/etc/pyflyby``, then ``~/.pyflyby``,
then the per-directory ``.pyflyby``.


Mandatory imports
-----------------

Within a certain project you may have a policy to always include certain
imports.  For example, maybe you always want to do ``from __future__ import
division`` in all files.

You can put the following in any file reachable from ``$PYFLYBY_PATH``::

  __mandatory_imports__ = ["from __future__ import division"]

To undo mandatory imports inherited from other ``.pyflyby`` files, use
``__forget_imports__`` (see above).


Canonicalize imports
--------------------

Sometimes you want every run of ``tidy-imports`` to automatically rename an import
to a new name.

You can put the following in any file reachable from ``$PYFLYBY_PATH``::

  __canonical_imports__ = {"oldmodule.oldfunction": "newmodule.newfunction"}

This is equivalent to running::

  tidy-imports --transform=oldmodule.oldfunction=newmodule.newfunction


Soapbox: avoid "star" imports
=============================

When programming in Python, a good software engineering practice is to avoid
using ``from foopackage import *`` in production code.

This style is a maintenance nightmare:

  * It becomes difficult to figure out where various symbols
    (functions/classes/etc) come from.

  * It's hard to tell what gets shadowed by what.

  * When the package changes in trivial ways, your code will be affected.
    Consider the following example: Suppose ``foopackage.py`` contains ``import
    sys``, and ``myprogram.py`` contains ``from foopackage import *; if
    some_condition: sys.exit(0)``.  If ``foopackage.py`` changes so that ``import
    sys`` is removed, ``myprogram.py`` is now broken because it's missing ``import
    sys``.

To fix such code, you can run ``tidy-imports --replace-star-imports`` to
automatically replace star imports with the specific needed imports.

Per-Project configuration of tidy-imports
=========================================

You can configure Pyflyby on a per-repository basis by using the
``[tool.pyflyby]`` section of ``pyproject.toml`` files. Pyflyby will look in current
working directory and all it's parent until it find a ``pyproject.toml`` file from
which it will load the defaults.


Most of the long command line flags default values can be configured in this
section. Simply use the long form option name by replacing dashes ``-`` by
underscore ``_``. For long option that have the form ``--xxx`` and ``--no-xxx``, you
can assign a boolean to ``xxx``. For example::

.. code:: toml

    [tool.pyflyby]
    add_missing=true
    from_spaces=7
    remove_unused=false

To exclude files from ``tidy-imports``, add an exclusion pattern to
``tool.pyflyby.tidy-imports.exclude``:

.. code:: toml

    [tool.pyflyby.tidy-imports]
    exclude = [
        "foo.py",
        "baz/*.py"
    ]

Exclusions are assumed to be relative to the project root if a ``pyproject.toml`` exists, unless an
absolute path is specified. Consult the documentation for ``pathlib.Path.match`` for information about
valid exclusion patterns.

Emacs support
=============

* To get a ``M-x tidy-imports`` command in GNU Emacs, add to your ``~/.emacs``::

    (load "/<site-packages>/pyflyby/share/emacs/site-lisp/pyflyby.el")


- Pyflyby.el doesn't yet work with XEmacs; patches welcome.


saveframe: A utility for debugging / reproducing an issue
=========================================================

PyFlyBy provides a utility named **saveframe** which can be used to save
information for debugging / reproducing an issue.

**Usage**: If you have a piece of code or a script that is failing due an issue
originating from upstream code, and you cannot share your private code as a reproducer,
use this utility to save relevant information to a file. Share the generated file with
the upstream team, enabling them to reproduce and diagnose the issue independently.

**Information saved in the file**: This utility captures and saves *error stack frames*
to a file. It includes the values of local variables from each stack frame, as well
as metadata about each frame and the exception raised by your code.

This utility comes with 2 interfaces:

1. **A function**: For interactive usages such as IPython, Jupyter Notebook, or a
   debugger (pdb/ipdb), use **pyflyby.saveframe** function. To know how to use this
   function, checkout it's documentation:

.. code::

   In [1]: saveframe?

2. **A script**: For cli usages (like a failing script), use **pyflyby/bin/saveframe**
   script. To know how to use this script, checkout its documentation:

.. code::

   $ saveframe --help

Authorship
==========

This plugin was contributed back to the community by the `D. E. Shaw group
<https://www.deshaw.com/>`_.

.. image:: https://www.deshaw.com/assets/logos/blue_logo_417x125.png
   :target: https://www.deshaw.com
   :height: 75 px

Pyflyby is written by Karl Chen <quarl@8166.clguba.z.quarl.org>

We love contributions! Before you can contribute, please sign and submit this
`Contributor License Agreement (CLA) <https://www.deshaw.com/oss/cla>`_.
This CLA is in place to protect all users of this project.

License
=======

Pyflyby is released under a very permissive license, the MIT/X11 license; see
LICENSE.txt.


Release
=======

1. Check version number in `lib/python/pyflyby/_version.py`, maybe increase it.
2. Commit and tag if necessary, and push tags/commits.
3. Optional: Set SOURCE_DATE_EPOCH for reproducible build::

    export SOURCE_DATE_EPOCH=$(git show -s --format=%ct HEAD)

4. Build the SDIST::

    python setup.py sdist

5. Optional Repack the Sdist to make sure the ZIP only contain SOURCE_DATE_EPOCH
   date using IPython tools::

    python ~/dev/ipython/tools/retar.py dist/pyflyby-1.7.8.tar.gz
    shasum -a 256 dist/*

6. Optional, redo 4 & 5 to verify checksum is unchanged.
7. Upload using twine::

    twine upload dist/*

8. Check/update https://github.com/conda-forge/pyflyby-feedstock for new pyflyby
   release on conda-forge
