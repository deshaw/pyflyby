# Configuration file for the Sphinx documentation builder.

# -- Path setup --------------------------------------------------------------
import os
import sys
import importlib

sys.path.insert(0, os.path.abspath('../lib/python'))
sys.path.insert(0, os.path.abspath('..'))

# -- Project information -----------------------------------------------------
project = 'pyflyby'
copyright = '2019, Karl Chen'
author = 'Karl Chen'
# The full version, including alpha/beta/rc tags

release = importlib.metadata.version('pyflyby')

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.coverage',
    'sphinx.ext.napoleon',
    'sphinx_autodoc_typehints'
]
exclude_patterns = ['_build', 'Thumbs.db', '.DS_Store', 'cli']
autodoc_default_options = {
    'undoc-members': True,
    'private-members': True
}

autodoc_mock_imports = [
    "pyflyby._fast_iter_modules",
    "platformdirs",
    "prompt_toolkit",
]

html_theme_options = {
    'collapse_navigation': False,
    'navigation_depth': -1,
}
# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'
