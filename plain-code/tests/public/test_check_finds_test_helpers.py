import tempfile
from contextlib import chdir
from pathlib import Path

from click.testing import CliRunner
from plain.code.cli import check

PYPROJECT = """\
[project]
name = "scratch"
version = "0"
requires-python = ">=3.14"
"""

HELPERS = """\
def create_user() -> str:
    return "ada"
"""

TEST_FILE = """\
from helpers import create_user


def test_user() -> None:
    assert create_user() == "ada"
"""

OTHER_HELPER = """\
def create_invoice() -> int:
    return 1
"""

TEST_FILE_USING_BOTH = """\
from billing_helpers import create_invoice
from helpers import create_user


def test_both() -> None:
    assert create_user() == "ada"
    assert create_invoice() == 1
"""


def make_tests_directory() -> None:
    # With an `__init__.py` in it, the type checker takes `tests` for a
    # package and would look for `tests.helpers`.
    # Without one it finds the directory by itself.
    Path("tests").mkdir()
    Path("tests/__init__.py").write_text("")


def run_the_type_check() -> int:
    result = CliRunner().invoke(
        check, ["--skip-ruff", "--skip-oxc", "--skip-annotations"]
    )
    return result.exit_code


def test_a_test_file_imports_the_helper_module_beside_it_by_its_bare_name():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        make_tests_directory()
        Path("tests/helpers.py").write_text(HELPERS)
        Path("tests/test_users.py").write_text(TEST_FILE)

        exit_code = run_the_type_check()

    assert exit_code == 0


def test_the_projects_own_extra_paths_are_still_searched():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(
            PYPROJECT + '\n[tool.ty.environment]\nextra-paths = ["shared"]\n'
        )
        Path("shared").mkdir()
        Path("shared/billing_helpers.py").write_text(OTHER_HELPER)
        make_tests_directory()
        Path("tests/helpers.py").write_text(HELPERS)
        Path("tests/test_both.py").write_text(TEST_FILE_USING_BOTH)

        exit_code = run_the_type_check()

    assert exit_code == 0


def test_an_import_that_is_nowhere_is_still_an_error():
    with tempfile.TemporaryDirectory() as tmp, chdir(tmp):
        Path("pyproject.toml").write_text(PYPROJECT)
        make_tests_directory()
        Path("tests/test_users.py").write_text(TEST_FILE)

        exit_code = run_the_type_check()

    assert exit_code != 0
