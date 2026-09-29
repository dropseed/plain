import json
import tempfile
from contextlib import chdir
from pathlib import Path

from click.testing import CliRunner
from plain.code.cli import annotations

PYPROJECT = """\
[project]
name = "scratch"
version = "0"
requires-python = ">=3.14"
"""

UNTYPED = """\
def helper(value):
    return value
"""


def count_functions() -> int:
    result = CliRunner().invoke(annotations, ["--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["total_functions"]


def test_a_directory_named_test_is_source():
    # `plain.test`, and the `test` module a package ships its helpers in.
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        Path("shop/test").mkdir(parents=True)
        Path("shop/test/helpers.py").write_text(UNTYPED)

        assert count_functions() == 1


def test_a_tests_directory_is_left_out():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        Path("tests").mkdir()
        Path("tests/helpers.py").write_text(UNTYPED)

        assert count_functions() == 0


def test_a_file_named_like_a_test_is_left_out_wherever_it_is():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        Path("shop/test").mkdir(parents=True)
        Path("shop/test/test_helpers.py").write_text(UNTYPED)
        Path("shop/checkout_test.py").write_text(UNTYPED)

        assert count_functions() == 0


def test_a_directory_whose_name_starts_with_a_dot_is_never_looked_in():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        Path(".left_by_a_tool/deeper").mkdir(parents=True)
        Path(".left_by_a_tool/module.py").write_text(UNTYPED)
        Path(".left_by_a_tool/deeper/module.py").write_text(UNTYPED)
        Path("shop").mkdir()
        Path("shop/module.py").write_text(UNTYPED)

        assert count_functions() == 1
