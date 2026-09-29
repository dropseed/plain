"""
CLASSES AS TESTS: this file.

A class named `Test*` is collected as a group of tests until every test
class in this repository has been written as functions. These are the tests
of that, and they go when it does.
"""

import sys
import tempfile
from pathlib import Path

from plain.test import patch
from plain.test.runner.collection import collect_tests
from plain.test.runner.execution import run_tests


def write_tests(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def import_modules_from(root: Path):
    return patch(sys, "path", [str(root), *sys.path])


def test_collects_inherited_test_methods():
    root = write_tests(
        {
            "test_inherit.py": (
                "class Shared:\n"
                "    def test_from_base(self):\n"
                "        assert True\n"
                "\n"
                "class TestChild(Shared):\n"
                "    def test_own(self):\n"
                "        assert True\n"
                "    def test_from_base(self):\n"
                "        assert True  # override collects once\n"
            )
        }
    )
    tests, _ = collect_tests(["."], root=root)
    names = [t.name for t in tests]
    assert names == ["TestChild::test_from_base", "TestChild::test_own"]


def test_class_target_selects_all_its_methods():
    root = write_tests(
        {
            "test_target.py": (
                "class TestOne:\n"
                "    def test_a(self):\n"
                "        assert True\n"
                "    def test_b(self):\n"
                "        assert True\n"
                "\n"
                "def test_other():\n"
                "    assert True\n"
            )
        }
    )
    tests, _ = collect_tests(["test_target.py::TestOne"], root=root)
    assert [t.name for t in tests] == ["TestOne::test_a", "TestOne::test_b"]

    tests, _ = collect_tests(["test_target.py::TestOne::test_b"], root=root)
    assert [t.name for t in tests] == ["TestOne::test_b"]


def test_static_and_class_methods_are_tests_too():
    root = write_tests(
        {
            "test_methods.py": (
                "from plain.test import cases\n"
                "\n"
                "ran = []\n"
                "\n"
                "class TestGroup:\n"
                "    @staticmethod\n"
                "    def test_static():\n"
                "        ran.append('static')\n"
                "\n"
                "    @classmethod\n"
                "    def test_class(cls):\n"
                "        ran.append(cls.__name__)\n"
                "\n"
                "    @staticmethod\n"
                "    @cases(1, 2)\n"
                "    def test_static_cases(number):\n"
                "        ran.append(number)\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert errors == []
    assert [t.name for t in tests] == [
        "TestGroup::test_static",
        "TestGroup::test_class",
        "TestGroup::test_static_cases[1]",
        "TestGroup::test_static_cases[2]",
    ]
    run = run_tests(tests, lifecycles=[])
    assert len(run.passed) == 4


def test_a_static_method_that_takes_parameters_is_told_so():
    root = write_tests(
        {
            "test_methods.py": (
                "class TestGroup:\n"
                "    @staticmethod\n"
                "    def test_static(user):\n"
                "        assert True\n"
                "\n"
                "    @classmethod\n"
                "    def test_class(cls, user):\n"
                "        assert True\n"
            )
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "TestGroup::test_static(user) takes parameters" in message
    assert "TestGroup::test_class(user) takes parameters" in message


def test_a_class_made_from_an_imported_one_runs_the_tests_it_was_given():
    root = write_tests(
        {
            "bases_shared_by_collection_tests.py": (
                "class TestBase:\n    def test_in_base(self):\n        assert True\n"
            ),
            "test_made.py": (
                "from bases_shared_by_collection_tests import TestBase\n"
                "\n"
                "class TestMade(TestBase):\n"
                "    def test_own(self):\n"
                "        assert True\n"
            ),
        }
    )
    with import_modules_from(root):
        tests, errors = collect_tests(["test_made.py"], root=root)
    assert errors == []
    assert [t.name for t in tests] == ["TestMade::test_in_base", "TestMade::test_own"]


def test_a_class_imported_and_left_at_that_has_tests_nothing_runs():
    root = write_tests(
        {
            "classes_shared_by_collection_tests.py": (
                "class TestShared:\n"
                "    def test_in_shared_class(self):\n"
                "        assert False\n"
            ),
            "test_imports.py": (
                "from classes_shared_by_collection_tests import TestShared\n"
            ),
        }
    )
    with import_modules_from(root):
        tests, errors = collect_tests(["test_imports.py"], root=root)
    assert tests == []
    assert (
        "TestShared is defined in classes_shared_by_collection_tests, not in this file."
    ) in str(errors[0].error)
