#!/usr/bin/env python

# pyflyby/setup.py.

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import (absolute_import, division, print_function,
                        with_statement)

import glob
import os
import re
from   setuptools               import Command, setup
from   setuptools.command.test  import test as TestCommand
import subprocess
import sys
from   textwrap                 import dedent


PYFLYBY_HOME        = os.path.abspath(os.path.dirname(__file__))
PYFLYBY_PYPATH      = os.path.join(PYFLYBY_HOME, "lib/python")
PYFLYBY_DOT_PYFLYBY = os.path.join(PYFLYBY_HOME, ".pyflyby")

# Get the pyflyby version from pyflyby.__version__.
# We use exec instead to avoid importing pyflyby here.
version_vars = {}
version_fn = os.path.join(PYFLYBY_PYPATH, "pyflyby/_version.py")
exec(open(version_fn).read(), {}, version_vars)
version = version_vars["__version__"]


def read(fname):
    with open(os.path.join(PYFLYBY_HOME, fname)) as f:
        return f.read()


def list_python_source_files():
    results = []
    for fn in glob.glob("bin/*"):
        if not os.path.isfile(fn):
            continue
        with open(fn) as f:
            line = f.readline()
            if not re.match("^#!.*python", line):
                continue
        results.append(fn)
    results += glob.glob("lib/python/pyflyby/*.py")
    results += glob.glob("tests/*.py")
    return results


class TidyImports(Command):
    description = "tidy imports in pyflyby source files (for maintainer use)"

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        files = list_python_source_files()
        pyflyby_path = ":".join([
            os.path.join(PYFLYBY_HOME, "etc/pyflyby"),
            PYFLYBY_DOT_PYFLYBY,
            ])
        subprocess.call([
            "env",
            "PYFLYBY_PATH=%s" % (pyflyby_path,),
            "tidy-imports",
            # "--debug",
            "--uniform",
            ] + files)


class CollectImports(Command):
    description = "update pyflyby's own .pyflyby file from imports (for maintainer use)"

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        files = list_python_source_files()
        print("Rewriting", PYFLYBY_DOT_PYFLYBY)
        with open(PYFLYBY_DOT_PYFLYBY, 'w') as f:
            print(dedent("""
                # -*- python -*-
                #
                # This is the imports database file for pyflyby itself.
                #
                # To regenerate this file, run: setup.py collect_imports

                __mandatory_imports__ = [
                    'from __future__ import print_function',
                ]
            """).lstrip(), file=f)
            f.flush()
            subprocess.call(
                [
                    os.path.join(PYFLYBY_HOME, "bin/collect-imports"),
                    "--include=pyflyby",
                    "--uniform",
                ] + files,
                stdout=f)
        subprocess.call(["git", "diff", PYFLYBY_DOT_PYFLYBY])


class PyTest(TestCommand):
    user_options = [('pytest-args=', 'a', "Arguments to pass to py.test")]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.pytest_args = ['--doctest-modules', 'lib', 'tests']

    def finalize_options(self):
        TestCommand.finalize_options(self)
        self.test_args = []
        self.test_suite = True

    def run_tests(self):
        import pytest
        # We want to test the version of pyflyby in this repository.  It's
        # possible that some different version of pyflyby already got imported
        # in usercustomize, before we could set sys.path here.  If so, unload
        # it.
        if 'pyflyby' in sys.modules:
            print("setup.py: Unloading %s from sys.modules "
                  "(perhaps it got loaded in usercustomize?)"
                  % (sys.modules['pyflyby'].__file__,))
            del sys.modules['pyflyby']
            for k in sys.modules.keys():
                if k.startswith("pyflyby."):
                    del sys.modules[k]
        # Add our version of pyflyby to sys.path & PYTHONPATH.
        sys.path.insert(0, PYFLYBY_PYPATH)
        os.environ["PYTHONPATH"] = PYFLYBY_PYPATH
        # Run pytest.
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


setup(
    name = "pyflyby",
    version = version,
    author = "Karl Chen",
    author_email = "quarl@8166.clguba.z.quarl.org",
    description = ("pyflyby - Python development productivity tools, in particular automatic import management"),
    license = "MIT",
    keywords = "pyflyby py autopython autoipython productivity automatic imports autoimporter tidy-imports",
    url = "https://pypi.org/project/pyflyby/",
    project_urls={
          'Documentation': 'https://deshaw.github.io/pyflyby/',
          'Source'       : 'https://github.com/deshaw/pyflyby',
      },
    package_dir={'': 'lib/python'},
    packages=['pyflyby'],
    entry_points={'console_scripts':
                  '\n'.join([
                      'py=pyflyby._py:py_main',
                      'py{}=pyflyby._py:py_main'.format(str(sys.version_info[0])),
                  ])},
    scripts=[
        # TODO: convert these scripts into entry points (but leave stubs in
        # bin/ for non-installed usage)
        'bin/collect-exports',
        'bin/collect-imports',
        'bin/find-import',
        'bin/list-bad-xrefs',
        'bin/prune-broken-imports',
        'bin/pyflyby-diff',
        'bin/reformat-imports',
        'bin/replace-star-imports',
        'bin/tidy-imports',
        'bin/transform-imports',
    ],
    data_files=[
        ('libexec/pyflyby', [
            'libexec/pyflyby/colordiff', 'libexec/pyflyby/diff-colorize',
        ]),
        ('etc/pyflyby', glob.glob('etc/pyflyby/*.py')),
        ('share/doc/pyflyby', glob.glob('doc/*.txt')),
        ('share/emacs/site-lisp', ['lib/emacs/pyflyby.el']),
    ],
    long_description=read('README.rst'),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Topic :: Software Development",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Interpreters",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
    ],
    install_requires=['pyflakes', 'six'],
    python_requires=">=2.5, !=3.0.*, !=3.1.*, !=3.2.*, !=3.2.*, !=3.3.*, !=3.4.*,, !=3.5.*, !=3.6.*, <4",
    tests_require=['pexpect>=3.3', 'pytest', 'epydoc', 'rlipython', 'requests'],
    cmdclass = {
        'test'           : PyTest,
        'collect_imports': CollectImports,
        'tidy_imports'   : TidyImports,
    },
)
