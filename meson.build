project(
  'pyflyby',
  'cpp',
  version: run_command(['python', '-m', 'setuptools_scm'], check: true).stdout().strip(),
  default_options: 'cpp_std=c++17'
)

py_mod = import('python')
py = py_mod.find_installation(pure: false)
pybind11_dep = dependency('pybind11', version: '>=2.10.4')
includes = include_directories([ 'src' ])

subdir('lib/python/pyflyby')

install_data(
  ['libexec/pyflyby/colordiff', 'libexec/pyflyby/diff-colorize'],
  install_dir: py.get_install_dir(
    subdir: 'pyflyby/libexec/pyflyby',
  )
)

install_data(
  [
    './etc/pyflyby/canonical.py',
    './etc/pyflyby/common.py',
    './etc/pyflyby/forget.py',
    './etc/pyflyby/mandatory.py',
    './etc/pyflyby/numpy.py',
    './etc/pyflyby/std.py',
  ],
  install_dir: py.get_install_dir(
    subdir: 'pyflyby/etc/pyflyby',
  )
)

install_data(
  ['./lib/emacs/pyflyby.el'],
  install_dir: py.get_install_dir(
    subdir: 'pyflyby/share/emacs/site-lisp',
  )
)

install_data(
  [
    'bin/collect-exports',
    'bin/collect-imports',
    'bin/find-import',
    'bin/prune-broken-imports',
    'bin/pyflyby-diff',
    'bin/reformat-imports',
    'bin/replace-star-imports',
    'bin/saveframe',
    'bin/tidy-imports',
    'bin/transform-imports',
  ],
  install_dir: get_option('bindir')
)

py.extension_module(
  '_fast_iter_modules',
  'src/_fast_iter_modules.cpp',
  install: true,
  subdir: 'pyflyby',
  dependencies: [pybind11_dep],
  include_directories: includes
)
