# Configuration file for the Sphinx documentation builder.

# -- Path setup --------------------------------------------------------------
import os
import sys
sys.path.insert(0, os.path.abspath('../lib/python'))


# -- Project information -----------------------------------------------------
project = 'pyflyby'
copyright = '2019, Karl Chen'
author = 'Karl Chen'
# The full version, including alpha/beta/rc tags
release = '0.0.1'


# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.coverage',
    'sphinx.ext.napoleon',
    'sphinx_autodoc_typehints'
]
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store']
autodoc_default_options = {
    'undoc-members': True,
    'private-members': True
}

# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'