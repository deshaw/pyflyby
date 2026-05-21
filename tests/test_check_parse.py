# pyflyby/test_check_parse.py

# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/


from   pathlib                  import Path
import sys
import tempfile

from   pyflyby.check_parse      import (check_parse_main, find_python_files,
                                        parse_file)


def test_find_python_files_single_file():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.py"
        f.write_text("x = 1\n")
        assert find_python_files(f) == [f]


def test_find_python_files_single_non_py():
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "a.txt"
        f.write_text("not python")
        assert find_python_files(f) == []


def test_find_python_files_directory():
    with tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        (tmpp / "a.py").write_text("x = 1\n")
        (tmpp / "b.py").write_text("y = 2\n")
        (tmpp / "c.txt").write_text("text\n")
        result = find_python_files(tmpp)
        names = sorted(p.name for p in result)
        assert names == ["a.py", "b.py"]


def test_find_python_files_excludes_hidden_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        hidden = tmpp / ".hidden"
        hidden.mkdir()
        (hidden / "skip.py").write_text("x = 1\n")
        (tmpp / "keep.py").write_text("x = 1\n")
        names = sorted(p.name for p in find_python_files(tmpp))
        assert names == ["keep.py"]


def test_find_python_files_excludes_pycache():
    with tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        cache = tmpp / "__pycache__"
        cache.mkdir()
        (cache / "skip.py").write_text("x = 1\n")
        venv = tmpp / "venv"
        venv.mkdir()
        (venv / "skip.py").write_text("x = 1\n")
        (tmpp / "keep.py").write_text("x = 1\n")
        names = sorted(p.name for p in find_python_files(tmpp))
        assert names == ["keep.py"]


def test_find_python_files_recursive():
    with tempfile.TemporaryDirectory() as tmp:
        tmpp = Path(tmp)
        sub = tmpp / "sub"
        sub.mkdir()
        (sub / "a.py").write_text("x = 1\n")
        (tmpp / "b.py").write_text("y = 2\n")
        names = sorted(p.name for p in find_python_files(tmpp))
        assert names == ["a.py", "b.py"]


def test_parse_file_valid():
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False
    ) as f:
        f.write("x = 1\ny = 2\n")
        path = Path(f.name)
    try:
        success, err = parse_file(path)
        assert success
        assert err == ""
    finally:
        path.unlink()


def test_parse_file_invalid_syntax():
    # Files where ast.parse fails are NOT errors (only pyflyby-specific
    # parse failures are reported).
    with tempfile.NamedTemporaryFile(
        "w", suffix=".py", delete=False
    ) as f:
        f.write("def bad(:\n")
        path = Path(f.name)
    try:
        success, err = parse_file(path)
        assert success
        assert err == ""
    finally:
        path.unlink()


def test_parse_file_undecodable():
    with tempfile.NamedTemporaryFile(
        suffix=".py", delete=False
    ) as f:
        # Invalid UTF-8 bytes
        f.write(b"\xff\xfe\xfa\xfb invalid")
        path = Path(f.name)
    try:
        success, err = parse_file(path)
        assert success
        assert err == ""
    finally:
        path.unlink()


def test_check_parse_main_no_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_parse"])
    result = check_parse_main()
    assert isinstance(result, str)
    assert "Usage:" in result


def test_check_parse_main_too_many_args(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["check_parse", "a", "b"])
    result = check_parse_main()
    assert isinstance(result, str)
    assert "Usage:" in result


def test_check_parse_main_empty_dir(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(sys, "argv", ["check_parse", tmp])
        result = check_parse_main()
        assert result == "No Python files found"


def test_check_parse_main_success(monkeypatch, capsys):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "good.py").write_text("x = 1\n")
        (Path(tmp) / "other.py").write_text("def f():\n    return 42\n")
        monkeypatch.setattr(sys, "argv", ["check_parse", tmp])
        # Force non-TTY mode so progress output is bounded
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
        result = check_parse_main()
        assert result == 0
        out = capsys.readouterr().out
        assert "2 files parsed successfully" in out or "2/2" in out
