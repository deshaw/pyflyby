# pyflyby/test_dynimp.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/


import sys

import pytest

from   pyflyby._dynimp          import (DictFinder, DictLoader, _add_import,
                                        add_import, inject, module_dict)


def test_dict_loader_create_module():
    loader = DictLoader("dummy_mod", "x = 1")
    assert loader.create_module(None) is None


def test_dict_loader_exec_module():
    loader = DictLoader("dummy", "x = 42")

    class FakeModule:
        pass
    m = FakeModule()
    m.__dict__ = {}
    loader.exec_module(m)
    assert m.__dict__["x"] == 42


def test_dict_finder_returns_none_for_unknown():
    finder = DictFinder()
    assert finder.find_spec("definitely_not_a_module_xyz", None) is None


def test_dict_finder_returns_spec_for_known():
    name = "_pyflyby_test_finder_known_mod"
    module_dict[name] = "y = 99"
    try:
        finder = DictFinder()
        spec = finder.find_spec(name, None)
        assert spec is not None
        assert spec.name == name
    finally:
        module_dict.pop(name, None)


def test_inject_adds_finder():
    n_before = len(sys.meta_path)
    inject()
    try:
        assert len(sys.meta_path) == n_before + 1
        assert isinstance(sys.meta_path[0], DictFinder)
    finally:
        # Remove the finder we just added
        sys.meta_path.pop(0)


def test_add_import_no_ipython_strict_false():
    # In test environments without IPython auto-importer set up, add_import
    # with strict=False should not raise.
    add_import("foo_xyz", "foo_xyz = 1", strict=False)


def test_add_import_no_ipython_strict_true():
    # With strict=True, it raises because we are not in IPython with
    # the pyflyby extension loaded.
    with pytest.raises((ImportError, ValueError)):
        add_import("foo_xyz2", "foo_xyz2 = 1", strict=True)
