# pyflyby/check_parse.py
"""
Module to parse all Python files in a given path using PythonBlock to detect parsing issues.

This is specifically useful for catching bugs in pyflyby's _parse.py
implementation by scanning large codebase, typically `cpython`, or linters that
usually have many usefull testcases like `ruff`

Usage:
    python -m pyflyby.check_parse <path>
"""

import ast
from   pathlib                  import Path
import sys
from   typing                   import List, Tuple
import warnings

from   pyflyby._parse           import PythonBlock


def find_python_files(path: Path) -> List[Path]:
    """Find all Python files in the given path recursively.

    Exclude venv ans other kind of files.
    """
    if path.is_file():
        return [path] if path.suffix == ".py" else []

    python_files = []
    for item in path.rglob("*.py"):
        if item.is_file():
            # Skip common directories that might have issues or be too large
            if any(part.startswith(".") for part in item.parts):
                continue
            if any(part in ("__pycache__", "venv", "env") for part in item.parts):
                continue
            python_files.append(item)

    return sorted(python_files)


def parse_file(file_path: Path) -> Tuple[bool, str]:
    """
    Try to parse a Python file using PythonBlock.

    Only reports errors if PythonBlock fails but ast.parse succeeds,
    indicating a pyflyby-specific parsing issue.

    Scanning CPython/Ruff can trigger many errors in ast.parse because of many
    test cases failing on purpose.

    Returns:
        (success, error_message) tuple
    """
    try:
        content = file_path.read_text()
    except UnicodeDecodeError:
        return True, ""

    # Try parsing with ast to see if it's a valid Python file
    ast_has_warning = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            ast.parse(content, filename=file_path, type_comments=True)
    except SyntaxError:
        return True, ""
    except SyntaxWarning:
        ast_has_warning = True

    # Now try parsing with PythonBlock
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            block = PythonBlock(content, auto_flags=True)

            # Access the annotated_ast_node to ensure it's created without errors
            _ = block.annotated_ast_node

    except SyntaxWarning as e:
        # If ast also had a warning, it's not pyflyby-specific
        if ast_has_warning:
            return True, ""
        return False, f"SyntaxWarning: {e}"
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    return True, ""


def check_parse_main():
    """Main entry point for check-parse command.

    Returns:
        0 on success, error message string on failure
    """
    if len(sys.argv) != 2:
        return """Usage: python -m pyflyby.check_parse <path>

Parse all Python files in the given path using PythonBlock to detect
pyflyby-specific parsing issues. This compares pyflyby's parser against
the standard library's ast.parse() to identify bugs in pyflyby's _parse.py.

Only reports errors that occur with pyflyby but not with ast.parse,
indicating pyflyby-specific bugs rather than legitimate Python syntax errors.
"""

    path = Path(sys.argv[1]).resolve()

    print(f"Searching for Python files in: {path}")
    python_files = find_python_files(path)

    if not python_files:
        return "No Python files found"

    print(f"Found {len(python_files)} Python file(s)")

    failed_files = []
    success_count = 0
    total = len(python_files)
    is_tty = sys.stdout.isatty()
    last_printed_progress = -1

    for i, file_path in enumerate(python_files, 1):
        progress = i * 100 // total

        if is_tty:
            # Display progress bar with fancy ASCII blocks
            bar_length = 40
            filled = bar_length * i // total
            bar = "█" * filled + "░" * (bar_length - filled)
            print(f"\rParsing: {bar} {i}/{total} ({progress}%)", end="", flush=True)
        else:
            # Print every 5% when not a TTY
            if progress >= last_printed_progress + 5:
                print(f"Progress: {progress}% ({i}/{total})")
                last_printed_progress = progress

        success, error = parse_file(file_path)

        if success:
            success_count += 1
        else:
            # Clear progress bar and print error
            if is_tty:
                print(f"\r{' ' * 80}\r", end="")
            print(f"✗ {file_path}")
            print(f"  {error}")
            failed_files.append((file_path, error))

    # Clear progress bar
    if is_tty:
        print(f"\r{' ' * 80}\r", end="")

    print(f"Results: {success_count}/{total} files parsed successfully")

    if failed_files:
        error_msg = f"\n{len(failed_files)} file(s) failed:\n"
        for file_path, error in failed_files:
            error_msg += f"  - {file_path}\n"
            error_msg += f"    {error}\n"
        return error_msg
    print("✓ All files parsed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(check_parse_main())
