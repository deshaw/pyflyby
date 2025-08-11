project(
  'pyflyby',
  'cpp',
  version: '0.0.1'
)

py_mod = import('python')
py = py_mod.find_installation()

pybind11_dep = dependency('pybind11', version: '>=2.10.4')

includes = include_directories(
  [
    'src'
  ]
)

message('Installation directory:           ', py.get_install_dir(subdir: 'pyflyby'))
message('Installation directory (not pure):           ', py.get_install_dir(pure: false))
message('Installation directory (pure):           ', py.get_install_dir(pure: true))

# subdir('lib')

install_data(
  ['libexec/pyflyby/colordiff', 'libexec/pyflyby/diff-colorize'],
  install_dir: py.get_install_dir(
    subdir: 'libexec/pyflyby',
    pure: true, # Not really pure, these are bash scripts, but we're not compiling them.
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
    subdir: 'etc/pyflyby',
    pure: true,
  )
)

install_data(
  ['./lib/emacs/pyflyby.el'],
  install_dir: py.get_install_dir(
    subdir: 'share/emacs/site-lisp',
    pure: true,
  )
)
