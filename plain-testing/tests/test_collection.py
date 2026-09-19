import tempfile
from pathlib import Path

from plain.test import raises
from plain.testing.collection import collect_tests


def write_tests(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def test_collects_functions_and_classes():
    root = write_tests(
        {
            "test_things.py": (
                "def test_one():\n"
                "    assert True\n"
                "\n"
                "class TestGroup:\n"
                "    def test_two(self):\n"
                "        assert True\n"
                "\n"
                "class TestHelperlike:\n"
                "    pass\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == [
        "test_things.py::test_one",
        "test_things.py::TestGroup::test_two",
    ]
    assert errors == []


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


def test_cases_expand_with_bound_arguments():
    root = write_tests(
        {
            "test_cases.py": (
                "from plain.test import cases\n"
                "\n"
                "@cases((1, 2, 3), (2, 2, 4))\n"
                "def test_add(a, b, total):\n"
                "    assert a + b == total\n"
            )
        }
    )
    tests, _ = collect_tests(["."], root=root)
    assert [t.name for t in tests] == ["test_add[0]", "test_add[1]"]
    for test in tests:
        test.func()  # cases are bound — runnable with no arguments


def test_unimportable_file_reported_without_stopping_collection():
    root = write_tests(
        {
            "test_broken.py": "import does_not_exist_anywhere\n",
            "test_fine.py": "def test_ok():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["test_fine.py::test_ok"]
    assert len(errors) == 1
    assert errors[0].path.name == "test_broken.py"


def test_missing_target_raises():
    root = write_tests({"test_x.py": "def test_ok():\n    assert True\n"})
    with raises(FileNotFoundError):
        collect_tests(["test_nope.py"], root=root)
