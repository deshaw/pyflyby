#!/usr/bin/env python

# pyflyby/setup.py.

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

from __future__ import absolute_import, division, with_statement

import glob
import os
from   setuptools               import setup
from   setuptools.command.test  import test as TestCommand
import sys

PYFLYBY_HOME = os.path.dirname(__file__)
PYFLYBY_PYPATH = os.path.join(PYFLYBY_HOME, "lib/python")

version_vars = {}
version_fn = os.path.join(PYFLYBY_PYPATH, "pyflyby/_version.py")
execfile(version_fn, {}, version_vars)
version = version_vars["__version__"]

def read(fname):
    with open(os.path.join(PYFLYBY_HOME, fname)) as f:
        return f.read()



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
        sys.path.insert(0, PYFLYBY_PYPATH)
        os.environ["PYTHONPATH"] = PYFLYBY_PYPATH
        errno = pytest.main(self.pytest_args)
        sys.exit(errno)


setup(
    name = "pyflyby",
    version = version,
    author = "Karl Chen",
    author_email = "quarl@8166.clguba.z.quarl.org",
    description = ("pyflyby - Python development productivity tools, in particular automatic import management"),
    license = "MIT",
    keywords = "pyflyby productivity automatic imports autoimporter tidy-imports",
    url = "http://packages.python.org/pyflyby",
    package_dir={'': 'lib/python'},
    packages=['pyflyby'],
    scripts=[
        'bin/collect-exports',
        'bin/collect-imports',
        'bin/create-imports',
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
    long_description=read('doc/README.txt'),
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Topic :: Software Development",
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Interpreters",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
    ],
    install_requires=['pyflakes'],
    tests_require=['pytest', 'epydoc'],
    cmdclass = {'test': PyTest},)
