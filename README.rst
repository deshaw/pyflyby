Pyflyby is a set of Python programming productivity tools.

For command-line interaction:
  * py: command-line multitool

For IPython interaction:
  * autoimporter: automatically imports symbols when needed.

For editing python source code:
  * tidy-imports:      adds missing 'import's, removes unused 'import's, and
                       also reformats 'import' blocks.
  * find-imports:      prints to stdout how to import a particular symbol.
  * reformat-imports:  reformats 'import' blocks
  * collect-imports:   prints out all the imports in a given set of files.
  * collect-exports:   prints out definitions in a given set of modules, in the
                       form of import statements.
  * transform-imports: renames imported modules/functions.

Quick start: Autoimporter + IPython
===================================

  $ py
      In [1]: re.search("[a-z]+", "....hello...").group(0)
      [PYFLYBY] import re
      Out[1]: 'hello'

      In [2]: chisqprob(arange(5), 2)
      [PYFLYBY] from numpy import arange
      [PYFLYBY] from scipy.stats import chisqprob
      Out[2]: [ 1.      0.6065  0.3679  0.2231  0.1353]

To load pyflyby into an existing IPython session as a 1-off:

  $ ipython
      In [1]: %load_ext pyflyby

To configure IPython/Jupyter Notebook to load pyflyby automatically:

  $ py pyflyby.install_in_ipython_config_file
     or
  $ echo 'c.InteractiveShellApp.extensions.append("pyflyby")' \
      >> ~/.ipython/profile_default/ipython_config.py

  $ ipython
      In [1]: b64decode('aGVsbG8=')
      [PYFLYBY] from base64 import b64decode
      Out[1]: 'hello'


Quick start: command-line multi-tool
====================================

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

Quick start: tidy-imports
=========================

To use tidy-imports, just specify the filename(s) to tidy.

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


Quick start: import libraries
=============================

Create a file named .pyflyby with lines such as::
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

Example:

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
members, and only then:

  $ ipython
  In [1]: nump<TAB>
  In [1]: numpy
  In [1]: numpy.arang<TAB>
  [PYFLYBY] import numpy
  In [1]: numpy.arange


The IPython "?" magic help (pinfo/pinfo2) automatically imports symbols first
if necessary:

  $ ipython
  In [1]: arange?
  [PYFLYBY] from numpy import arange
  ... Docstring: arange([start,] stop[, step,], dtype=None) ...

Other IPython magic commands work as well:

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


Implementation details
----------------------

The automatic importing happens at parse time, before code is executed.  The
namespace never contains entries for names that are not yet imported.

This method of importing at parse time contrasts with previous implementations
of automatic importing that use proxy objects.  Those implementations using
proxy objects don't work as well, because it is impossible to make proxy
objects behave perfectly.  For example, instance(x, T) will return the wrong
answer if either x or T is a proxy object.


Compatibility
-------------

Tested with:
  - Python 2.6, 2.7
  - IPython 0.10, 0.11, 0.12, 0.13, 1.0, 1.2, 2.0, 2.1, 2.2, 2.3, 2.4, 3.0,
    3.1, 3.2, 4.0.
  - IPython (text console), IPython Notebook, Spyder



Details: import libraries
=========================

Pyflyby uses "import libraries" that tell how to import a given symbol.

An import library file is simply a python source file containing 'import' (or
'from ... import ...') lines.  These can be generated automatically with
collect-imports and collect-exports.

Known imports
-------------

Find-imports, tidy-imports, and autoimport consult the database of known
imports to figure out where to get an import.  For example, if the
imports database contains::

    from numpy import arange, NaN

then when you type the following in IPython::

    print arange(10)

the autoimporter would automatically execute "from numpy import arange".

The database can be one file or multiple files.  This makes it easy to have
project-specific known_imports along with global and per-user defaults.

The PYFLYBY_PATH environment variable specifies which files to read.
This is a colon-separated list of filenames or directory names.  The default
is::

  PYFLYBY_PATH=/etc/pyflyby:~/.pyflyby:.../.pyflyby

If you set::

  PYFLYBY_PATH=/foo1/bar1:/foo2/bar2

then this replaces the default.

You can use a hyphen to include the default in the path.  If you set::

  PYFLYBY_PATH=/foo1/bar1:-:/foo2/bar2

then this reads /foo1/bar1, then the default locations, then /foo2/bar2.

In $PYFLYBY_PATH, ".../.pyflyby" (with _three_ dots) means that all ancestor
directories are searched for a member named ".pyflyby".

For example, suppose the following files exist:
  /etc/pyflyby/stuff.py
  /u/quarl/.pyflyby/blah1.py
  /u/quarl/.pyflyby/more/blah2.py
  /proj/share/mypythonstuff/.pyflyby
  /proj/share/mypythonstuff/foo/bar/.pyflyby/baz.py
  /.pyflyby

Further, suppose:
  * /proj is on a separate file system from /.
  * $HOME=/u/quarl

Then "tidy-imports /proj/share/mypythonstuff/foo/bar/quux/zot.py" will by
default use the following::

  /etc/pyflyby/stuff.py
  /u/quarl/.pyflyby/blah1.py
  /u/quarl/.pyflyby/more/blah2.py
  /proj/share/mypythonstuff/foo/bar/.pyflyby/baz.py
  /proj/share/mypythonstuff/.pyflyby (a file)

Notes:
  * /.pyflyby is not included, because traversal stops at file system
    boundaries, and in this example, /proj is on a different file system than
    /.
  * .pyflyby (in $HOME or near the target file) can be a file or a directory.
    If it is a directory, then it is recursively searched for ``*.py`` files.
  * The order usually doesn't matter, but if there are "forget" instructions
    (see below), then the order matters.  In the default $PYFLYBY_PATH,
    .../.pyflyby is placed last so that per-directory configuration can
    override per-user configuration, which can override systemwide
    configuration.


Forgetting imports
------------------

Occasionally you may have reason to tell pyflyby to "forget" entries from the
database of known imports.

You can put the following in any file reachable from $PYFLYBY_PATH:

  __forget_imports__ = ["from numpy import NaN"]

This is useful if you want to use a set of imports maintained by someone else
except for a few particular imports.

Entries in $PYFLYBY_PATH are processed left-to-right in the order specified,
so put the files containing these at the end of your $PYFLYBY_PATH.  By
default, tidy-imports and friends process /etc/pyflyby, then ~/.pyflyby,
then the per-directory .pyflyby.


Mandatory imports
-----------------

Within a certain project you may have a policy to always include certain
imports.  For example, maybe you always want to do "from __future__ import
division" in all files.

You can put the following in any file reachable from $PYFLYBY_PATH:

  __mandatory_imports__ = ["from __future__ import division"]

To undo mandatory imports inherited from other .pyflyby files, use
__forget_imports__.


Canonicalize imports
--------------------

Sometimes you want every run of tidy-imports to automatically rename an import
to a new name.

You can put the following in any file reachable from $PYFLYBY_PATH:

  __canonical_imports__ = {"oldmodule.oldfunction": "newmodule.newfunction"}

This is equivalent to running:
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
    Consider the following example: Suppose foopackage.py contains ``import
    sys``, and myprogram.py contains ``from foopackage import *; if
    some_condition: sys.exit(0)``.  If foopackage.py changes so that ``import
    sys`` is removed, myprogram.py is now broken because it's missing ``import
    sys``.

To fix such code, you can run ``tidy-imports --replace-star-imports`` to
automatically replace star imports with the specific needed imports.


Emacs support
=============

* To get a ``M-x tidy-imports`` command in GNU Emacs, add to your ~/.emacs:

    (load "/path/to/pyflyby/lib/emacs/pyflyby.el")


- Pyflyby.el doesn't yet work with XEmacs; patches welcome.


Authorship
==========

Pyflyby is written by Karl Chen <quarl@8166.clguba.z.quarl.org>


License
=======

Pyflyby is released under a very permissive license, the MIT/X11 license; see
LICENSE.txt.
