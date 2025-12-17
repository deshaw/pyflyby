# pyflyby/test_cmdline_changedexit1.py
#
# License for THIS FILE ONLY: CC0 Public Domain Dedication
# http://creativecommons.org/publicdomain/zero/1.0/

"""Tests for the CHANGEDEXIT1 action."""

import os
import subprocess
import sys
import tempfile

import pytest

PYFLYBY_HOME = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
BIN_DIR = os.path.join(PYFLYBY_HOME, "bin")

python = sys.executable


def pipe_with_exitcode(command, stdin="", cwd=None, env=None):
    """Run command and return (output, exit_code)."""
    proc = subprocess.Popen(
        [python] + command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=cwd,
        env=env
    )
    output, _ = proc.communicate(stdin.encode('utf-8'))
    return output.decode('utf-8').strip(), proc.returncode


@pytest.mark.parametrize(
    "code,expected_exitcode,description",
    [
        (
            "import os\n\nprint(os.path.join('a', 'b'))\n",
            0,
            "clean code"
        ),
        (
            "import sys\nimport os\n\nprint(os.path.join('a', 'b'))\n",
            1,
            "messy code with unused import"
        ),
    ],
)
def test_changedexit1_stdin(code, expected_exitcode, description):
    """Test that CHANGEDEXIT1 returns correct exit code for stdin input."""
    output, exitcode = pipe_with_exitcode(
        [BIN_DIR + "/tidy-imports", "--actions=CHANGEDEXIT1", "--no-add"],
        stdin=code
    )
    assert exitcode == expected_exitcode, (
        f"Expected exit code {expected_exitcode} for {description}, "
        f"got {exitcode}\nOutput: {output}"
    )


@pytest.mark.parametrize(
    "file_content,expected_exitcode,description",
    [
        (
            "import os\n\nprint(os.path.join('a', 'b'))\n",
            0,
            "clean file"
        ),
        (
            "import sys\nimport os\n\nprint(os.path.join('a', 'b'))\n",
            1,
            "file with unused import"
        ),
    ],
)
def test_changedexit1_file(file_content, expected_exitcode, description):
    """Test that CHANGEDEXIT1 returns correct exit code for file input."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w+", delete=False) as f:
        f.write(file_content)
        f.flush()
        temp_filename = f.name

    try:
        output, exitcode = pipe_with_exitcode(
            [BIN_DIR + "/tidy-imports", temp_filename, "--actions=CHANGEDEXIT1", "--no-add"]
        )
        assert exitcode == expected_exitcode, (
            f"Expected exit code {expected_exitcode} for {description}, "
            f"got {exitcode}\nOutput: {output}"
        )
    finally:
        os.unlink(temp_filename)
