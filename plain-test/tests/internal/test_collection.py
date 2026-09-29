import sys
import tempfile
from pathlib import Path

from plain.test import TestDefinitionError, case, cases, patch, raises
from plain.test.runner.collection import collect_tests
from plain.test.runner.execution import run_tests
from plain.test.runner.reporting import collection_error_text


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
    assert [t.name for t in tests] == ["test_add[1-2-3]", "test_add[2-2-4]"]
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


def test_objects_that_refuse_attribute_access_are_left_alone():
    # A test module can hold anything at module level — here a namespace
    # whose PEP 562 `__getattr__` raises for every name. Collection only
    # looks at functions and classes, so it never asks.
    root = write_tests(
        {
            "test_hostile.py": (
                "from types import ModuleType\n"
                "\n"
                "def _refuse(name):\n"
                "    raise RuntimeError(f'probed for {name!r}')\n"
                "\n"
                "hostile = ModuleType('hostile_namespace')\n"
                "hostile.__dict__['__getattr__'] = _refuse\n"
                "\n"
                "def test_one():\n"
                "    assert True\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["test_hostile.py::test_one"]
    assert errors == []


def test_parameters_nothing_passes_in_are_a_collection_error():
    root = write_tests(
        {
            "test_fixtures.py": (
                "def test_signup(db, client):\n"
                "    assert True\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
                "\n"
                "class TestGroup:\n"
                "    def test_in_class(self, settings):\n"
                "        assert True\n"
            ),
            "test_other.py": "def test_ok():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)

    # The rest of the run is untouched; the file with the problem runs nothing.
    assert [t.id for t in tests] == ["test_other.py::test_ok"]
    assert len(errors) == 1
    assert errors[0].path.name == "test_fixtures.py"

    error = errors[0].error
    assert isinstance(error, TestDefinitionError)
    message = str(error)
    # Every test that needs the fix is named, with the parameters in question.
    assert "test_signup(db, client) takes parameters" in message
    assert "TestGroup::test_in_class(settings) takes parameters" in message
    assert "test_fine" not in message
    assert "There are no fixtures" in message
    assert "@cases" in message


def test_parameters_with_defaults_and_wrapping_decorators_are_fine():
    root = write_tests(
        {
            "test_callable.py": (
                "import functools\n"
                "\n"
                "def passes_a_value_in(func):\n"
                "    @functools.wraps(func)\n"
                "    def wrapper(*args, **kwargs):\n"
                "        return func(*args, 'passed in', **kwargs)\n"
                "    return wrapper\n"
                "\n"
                "def test_default(limit=10):\n"
                "    assert limit == 10\n"
                "\n"
                "@passes_a_value_in\n"
                "def test_wrapped(value):\n"
                "    assert value == 'passed in'\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert errors == []
    assert [t.name for t in tests] == ["test_default", "test_wrapped"]
    for test in tests:
        test.func()


def test_cases_that_do_not_fit_the_parameters_are_a_collection_error():
    root = write_tests(
        {
            "test_arity.py": (
                "from plain.test import case, cases\n"
                "\n"
                "@cases((1, 2), case(1, 2, 3, id='too many'))\n"
                "def test_add(a, b):\n"
                "    assert a + b\n"
                "\n"
                "class TestGroup:\n"
                "    @cases(1, 2)\n"
                "    def test_in_class(self, value):\n"
                "        assert value\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    assert "test_add(a, b) doesn't fit its @cases" in message
    assert "case [too many] passes 3 values" in message
    # Its first case fits, and so does every case of the method.
    assert "case [1-2]" not in message
    assert "test_in_class" not in message


def test_a_second_cases_is_a_collection_error():
    root = write_tests(
        {
            "test_stacked.py": (
                "from plain.test import cases\n"
                "\n"
                "@cases('a', 'b')\n"
                "@cases(1, 2)\n"
                "def test_pairs(letter, number):\n"
                "    assert True\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert tests == []
    assert len(errors) == 1
    assert isinstance(errors[0].error, TestDefinitionError)
    assert "test_pairs already has @cases" in str(errors[0].error)


def test_a_decorator_used_wrongly_says_which_line_of_the_file():
    root = write_tests(
        {
            "test_bare.py": (
                "from plain.test import skip\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
                "\n"
                "@skip\n"
                "def test_never():\n"
                "    assert True\n"
            )
        }
    )
    _, errors = collect_tests(["."], root=root)
    assert isinstance(errors[0].error, TestDefinitionError)
    assert str(errors[0].error) == 'line 6: @skip requires a reason: @skip("why")'


def test_a_definition_error_is_printed_as_its_message():
    error = TestDefinitionError("line 6: @skip requires a reason")
    assert collection_error_text(error) == "line 6: @skip requires a reason"


def test_an_error_of_the_test_files_own_is_printed_with_its_traceback():
    root = write_tests(
        {
            "test_broken.py": (
                "def load_settings():\n"
                "    return UNDEFINED_NAME\n"
                "\n"
                "SETTINGS = load_settings()\n"
                "\n"
                "def test_one():\n"
                "    assert True\n"
            )
        }
    )
    _, errors = collect_tests(["."], root=root)
    text = collection_error_text(errors[0].error)
    lines = text.splitlines()
    assert lines[0] == "Traceback (most recent call last):"
    # It starts at the test file. How the runner got there isn't the reader's
    # problem.
    assert lines[1].startswith(f'  File "{root.resolve() / "test_broken.py"}", line 4')
    assert ", line 2, in load_settings" in text
    assert lines[-1] == "NameError: name 'UNDEFINED_NAME' is not defined"
    assert "collection.py" not in text


def test_a_syntax_error_names_the_file_and_the_line():
    root = write_tests({"test_broken.py": "def test_one(:\n    assert True\n"})
    _, errors = collect_tests(["."], root=root)
    text = collection_error_text(errors[0].error)
    assert text.splitlines()[0] == (
        f'  File "{root.resolve() / "test_broken.py"}", line 1'
    )
    assert "SyntaxError" in text.splitlines()[-1]
    assert "Traceback" not in text


def test_skip_test_skips_one_case_and_runs_the_others():
    root = write_tests(
        {
            "test_some_cases.py": (
                "from plain.test import case, cases, skip_test\n"
                "\n"
                "@cases(\n"
                "    case('text', id='text'),\n"
                "    case('encrypted', id='encrypted'),\n"
                ")\n"
                "def test_field(kind):\n"
                "    if kind == 'encrypted':\n"
                "        skip_test('Encrypted fields have no conditions')\n"
                "    assert kind == 'text'\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert errors == []

    run = run_tests(tests, lifecycles=[])
    assert [(r.test.name, r.outcome) for r in run.results] == [
        ("test_field[text]", "passed"),
        ("test_field[encrypted]", "skipped"),
    ]
    assert run.results[1].skip_reason == "Encrypted fields have no conditions"


def test_a_conftest_is_a_collection_error_wherever_it_is():
    root = write_tests(
        {
            "conftest.py": "import pytest\n",
            "accounts/conftest.py": "import pytest\n",
            "accounts/test_users.py": "def test_user():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["accounts/test_users.py::test_user"]
    assert [error.path for error in errors] == [
        root.resolve() / "conftest.py",
        root.resolve() / "accounts" / "conftest.py",
    ]
    assert all(isinstance(error.error, TestDefinitionError) for error in errors)


def test_a_conftest_in_a_directory_that_is_never_searched_is_not_reported():
    root = write_tests(
        {
            ".venv/lib/conftest.py": "",
            "node_modules/thing/conftest.py": "",
            "node_modules/thing/test_theirs.py": "def test_x():\n    assert True\n",
            "test_one.py": "def test_one():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["test_one.py::test_one"]
    assert errors == []


def test_a_conftest_above_a_single_file_target_is_found():
    root = write_tests(
        {
            "conftest.py": "import pytest\n",
            "accounts/conftest.py": "import pytest\n",
            "billing/conftest.py": "import pytest\n",
            "accounts/test_users.py": "def test_user():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["accounts/test_users.py"], root=root)
    assert len(tests) == 1
    # The ones pytest would have applied to that file, and not billing's.
    assert [error.path for error in errors] == [
        root.resolve() / "conftest.py",
        root.resolve() / "accounts" / "conftest.py",
    ]


def test_a_conftest_is_reported_once_for_overlapping_targets():
    root = write_tests(
        {
            "conftest.py": "import pytest\n",
            "test_one.py": "def test_one():\n    assert True\n",
        }
    )
    _, errors = collect_tests([".", "test_one.py"], root=root)
    assert len(errors) == 1


def test_a_conftest_names_its_fixtures_without_being_imported():
    root = write_tests(
        {
            "conftest.py": (
                "import pytest\n"
                "import a_module_that_is_not_installed\n"
                "\n"
                "@pytest.fixture\n"
                "def user(db):\n"
                "    return object()\n"
                "\n"
                "@pytest.fixture(scope='session')\n"
                "def server():\n"
                "    yield\n"
                "\n"
                "@pytest.fixture(autouse=True)\n"
                "def no_network(monkeypatch):\n"
                "    pass\n"
                "\n"
                "def a_plain_function():\n"
                "    pass\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "Fixtures in this file: user, server" in message
    assert "Autouse fixtures in this file: no_network" in message
    assert "a_plain_function" not in message


def test_only_a_tests_directory_refuses_imports_through_its_name():
    # Without a helper directory, the root's own name means nothing: a
    # project directory can be called anything, `plain` included.
    root = write_tests({})
    project = root / "plain"
    project.mkdir()
    (project / "test_one.py").write_text(
        "from plain.test import raises\n\ndef test_one():\n    assert raises\n"
    )
    tests, errors = collect_tests(["."], root=project)
    assert errors == []
    assert len(tests) == 1


def test_every_import_problem_in_a_file_is_reported_together():
    root = write_tests(
        {
            "tests/helpers.py": "value = 1\n",
            "tests/test_one.py": (
                "import tests.helpers\n"
                "from tests import helpers\n"
                "from . import helpers as mine\n"
                "\n"
                "def test_one():\n"
                "    from ..helpers import value\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root, helper_directory=root / "tests")
    assert len(errors) == 1
    assert isinstance(errors[0].error, TestDefinitionError)
    message = str(errors[0].error)
    assert "line 1: `import tests.helpers` should be `import helpers`" in message
    assert "line 2: `from tests import helpers` should be `import helpers`" in message
    assert (
        "line 3: `from . import helpers as mine` should be `import helpers as mine`"
    ) in message
    assert (
        "line 6: `from ..helpers import value` should be `from helpers import value`"
    ) in message


# What looks like a test and can't be run


def test_a_test_that_yields_is_a_collection_error():
    root = write_tests(
        {
            "test_yields.py": (
                "import functools\n"
                "\n"
                "def test_sync():\n"
                "    assert False\n"
                "    yield\n"
                "\n"
                "async def test_async():\n"
                "    assert False\n"
                "    yield\n"
                "\n"
                "def keeps_its_name(func):\n"
                "    @functools.wraps(func)\n"
                "    def wrapper():\n"
                "        return func()\n"
                "    return wrapper\n"
                "\n"
                "@keeps_its_name\n"
                "def test_wrapped():\n"
                "    assert False\n"
                "    yield\n"
                "\n"
                "class TestGroup:\n"
                "    def test_method(self):\n"
                "        assert False\n"
                "        yield\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert tests == []
    assert len(errors) == 1
    assert isinstance(errors[0].error, TestDefinitionError)
    message = str(errors[0].error)
    for name in ("test_sync", "test_async", "test_wrapped", "TestGroup::test_method"):
        assert f"{name}() has a `yield` in it" in message
    assert "test_fine" not in message
    # What a pytest test that yielded becomes, either kind.
    assert "@cases(...)" in message
    assert "`@contextmanager`" in message


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


def test_a_static_method_that_takes_fixtures_is_told_so():
    root = write_tests(
        {
            "test_methods.py": (
                "class TestGroup:\n"
                "    @staticmethod\n"
                "    def test_static(db):\n"
                "        assert True\n"
                "\n"
                "    @classmethod\n"
                "    def test_class(cls, db):\n"
                "        assert True\n"
            )
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "TestGroup::test_static(db) takes parameters" in message
    assert "TestGroup::test_class(db) takes parameters" in message


def test_a_unittest_testcase_is_a_collection_error_whatever_it_is_called():
    root = write_tests(
        {
            "test_unittest.py": (
                "import unittest\n"
                "from unittest import TestCase\n"
                "\n"
                "class UserTests(unittest.TestCase):\n"
                "    def test_it(self):\n"
                "        self.assertEqual(1, 2)\n"
                "\n"
                "class TestNamedOurWay(TestCase):\n"
                "    def setUp(self):\n"
                "        self.user = 'a user'\n"
                "    def test_it(self):\n"
                "        assert self.user\n"
            ),
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    assert "UserTests is a unittest.TestCase." in message
    assert "TestNamedOurWay is a unittest.TestCase." in message
    # What to write instead is said once for the two of them.
    assert message.count("unittest isn't run here") == 1
    assert "setUp()" in message
    # The class that was imported to be the base is not one of them.
    assert "TestCase is a unittest.TestCase" not in message


def import_modules_from(root: Path):
    return patch(sys, "path", [str(root), *sys.path])


def test_a_test_imported_from_another_module_is_a_collection_error():
    root = write_tests(
        {
            "checks_shared_by_collection_tests.py": (
                "def test_shared():\n"
                "    assert False\n"
                "\n"
                "def test_connection():\n"
                "    return 'not a test: the app calls this'\n"
                "\n"
                "class TestShared:\n"
                "    def test_in_shared_class(self):\n"
                "        assert False\n"
                "\n"
                "class TestBase:\n"
                "    def test_in_base(self):\n"
                "        assert True\n"
            ),
            "test_imports.py": (
                "from checks_shared_by_collection_tests import (\n"
                "    TestBase,\n"
                "    TestShared,\n"
                "    test_connection as check_connection,\n"
                "    test_shared,\n"
                ")\n"
                "\n"
                "class TestMade(TestBase):\n"
                "    def test_own(self):\n"
                "        assert check_connection()\n"
            ),
        }
    )
    with import_modules_from(root):
        tests, errors = collect_tests(["test_imports.py"], root=root)
    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    listed = message.split("\n\n")[1]
    assert listed == (
        "  TestShared is defined in checks_shared_by_collection_tests, "
        "not in this file.\n"
        "  test_shared is defined in checks_shared_by_collection_tests, "
        "not in this file."
    )
    # One imported under another name is not a test, and one imported to be
    # a base class has its tests run by the class made from it. Neither is
    # listed.
    assert "A test is run by the file that defines it" in message


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


# A conftest, wherever the target points


def test_a_conftest_above_a_directory_target_is_found():
    root = write_tests(
        {
            "conftest.py": "import pytest\n",
            "accounts/conftest.py": "import pytest\n",
            "accounts/users/test_users.py": "def test_user():\n    assert True\n",
            "billing/conftest.py": "import pytest\n",
        }
    )
    expected = [
        root.resolve() / "conftest.py",
        root.resolve() / "accounts" / "conftest.py",
    ]
    for target in (
        "accounts/users",
        "accounts/users/test_users.py",
        "accounts/users/test_users.py::test_user",
    ):
        tests, errors = collect_tests([target], root=root)
        assert len(tests) == 1
        assert [error.path for error in errors] == expected


def test_a_conftest_comes_before_the_files_that_used_it():
    root = write_tests(
        {
            "accounts/conftest.py": "import pytest\n",
            "accounts/test_users.py": "def test_user(db):\n    assert True\n",
            "test_first.py": "def test_first(db):\n    assert True\n",
        }
    )
    _, errors = collect_tests(["."], root=root)
    # The conftest is found in a directory that is searched after the
    # first test file, and is still the first thing said.
    assert [error.path.name for error in errors] == [
        "conftest.py",
        "test_first.py",
        "test_users.py",
    ]


# What a fixture was, and what to write


def test_a_parameter_that_was_a_known_fixture_says_what_to_write():
    root = write_tests(
        {
            "test_fixtures.py": (
                "def test_signup(db, settings, monkeypatch, tmp_path, caplog):\n"
                "    assert True\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "db           1 test  delete it: every test already runs" in message
    assert "settings     1 test  `with override_settings(NAME=value):`" in message
    assert 'monkeypatch  1 test  `with patch(target, "name", value):`' in message
    assert "tmp_path     1 test  `with tempfile.TemporaryDirectory()" in message
    assert "caplog       1 test  `with capture_logs() as logs:`" in message


def test_a_parameter_that_was_a_conftest_fixture_says_which_conftest():
    root = write_tests(
        {
            "conftest.py": (
                "import pytest\n\n@pytest.fixture\ndef kid(db):\n    return 'a kid'\n"
            ),
            "test_views.py": (
                "def test_passbook(kid, account, limit=3):\n    assert True\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[1].error)
    assert "test_passbook(kid, account, limit=3) takes parameters" in message
    assert "kid      1 test  a fixture in conftest.py" in message
    # One nothing is known about has its count and no more.
    assert message.endswith("  account  1 test")
    # One with a default is not something to fix.
    assert "limit  " not in message


def test_a_file_with_many_tests_to_fix_says_how_many_and_not_which():
    tests_asking = "".join(
        f"def test_number_{number}(db, org):\n    assert True\n\n"
        for number in range(12)
    )
    root = write_tests(
        {"test_many.py": tests_asking + "def test_other(org):\n    assert True\n"}
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "13 tests take parameters, and nothing passes them in." in message
    assert "test_number_3" not in message
    assert "db   12 tests  delete it" in message
    assert "org  13 tests" in message


def test_what_there_is_instead_of_fixtures_is_said_once():
    root = write_tests(
        {
            "test_a.py": "def test_a(db):\n    assert True\n",
            "test_b.py": "def test_b(db):\n    assert True\n",
            "test_c.py": "def test_c(db):\n    assert True\n",
        }
    )
    _, errors = collect_tests(["."], root=root)
    messages = [str(error.error) for error in errors]
    assert [message.count("There are no fixtures") for message in messages] == [
        1,
        0,
        0,
    ]
    for message in messages[1:]:
        assert "test_b(db) takes" in message or "test_c(db) takes" in message
        assert "What to write instead is in the error for test_a.py." in message
    # Each is still the one kind of error there is.
    assert all(type(error.error) is TestDefinitionError for error in errors)


def test_with_a_conftest_it_is_the_conftest_that_says_it():
    root = write_tests(
        {
            "conftest.py": "import pytest\n",
            "test_a.py": "def test_a(db):\n    assert True\n",
        }
    )
    _, errors = collect_tests(["."], root=root)
    assert "There are no\nfixtures" in str(errors[0].error)
    # The file says what its own parameters were, and no more.
    assert str(errors[1].error) == (
        "These tests can't be run as written:\n"
        "\n"
        "  test_a(db) takes parameters, and nothing passes them in.\n"
        "\n"
        "  db  1 test  delete it: every test already runs in a transaction "
        "that is rolled back"
    )


# A file that imports pytest


def test_a_file_that_imports_pytest_says_what_replaces_what_it_uses():
    root = write_tests(
        {
            "test_pytest.py": (
                '"""A docstring."""\n'
                "\n"
                "import pytest\n"
                "\n"
                "@pytest.fixture\n"
                "def user(db):\n"
                "    return 'a user'\n"
                "\n"
                "@pytest.mark.parametrize('n', [1, 2])\n"
                "def test_numbers(n):\n"
                "    with pytest.raises(ValueError):\n"
                "        int('x')\n"
                "    with pytest.raises(KeyError):\n"
                "        {}['x']\n"
                "\n"
                "@pytest.mark.slow\n"
                "def test_slow():\n"
                "    assert pytest.approx(0.3) == 0.1 + 0.2\n"
            ),
            "test_fine.py": "def test_fine():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["test_fine.py::test_fine"]
    assert len(errors) == 1
    error = errors[0].error
    assert type(error) is TestDefinitionError
    assert error.line == 3
    message = str(error)
    assert "line 3: `import pytest`" in message
    assert (
        "It uses pytest.raises ×2, pytest.fixture, pytest.mark.parametrize, "
        "pytest.approx, pytest.mark.slow."
    ) in message
    assert "pytest isn't used here, and isn't installed." in message
    assert "What replaces what this file uses:" in message
    assert "pytest.raises: `raises`, from plain.test." in message
    assert "pytest.mark.parametrize: `@cases`, from plain.test" in message
    assert "pytest.fixture: a helper function the test calls in its body." in message
    assert 'pytest.mark.slow: `@tag("name")`, from plain.test.' in message
    assert "pytest.approx: `math.isclose(a, b, abs_tol=...)`." in message
    assert 'plain docs test --search "Migrating from pytest"' in message
    # It was read, not run: nothing got as far as the import failing.
    assert "ModuleNotFoundError" not in message


@cases(
    case("from pytest import raises\n", "`from pytest import raises`", id="from"),
    case("import pytest as pt\n", "`import pytest as pt`", id="as"),
    case("import pytest_mock\n", "`import pytest_mock`", id="a plugin"),
    case(
        "def test_x():\n    import pytest\n",
        "line 2: `import pytest`",
        id="inside a test",
    ),
)
def test_pytest_is_found_however_it_is_imported(source, written):
    root = write_tests({"test_pytest.py": source})
    _, errors = collect_tests(["."], root=root)
    assert type(errors[0].error) is TestDefinitionError
    assert written in str(errors[0].error)


def test_names_taken_from_pytest_are_counted_under_their_own_names():
    root = write_tests(
        {
            "test_pytest.py": (
                "import pytest as pt\n"
                "from pytest import raises as throws\n"
                "\n"
                "def test_x():\n"
                "    with throws(ValueError):\n"
                "        pt.skip('not here')\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root)
    message = str(errors[0].error)
    assert "It uses pytest.raises, pytest.skip." in message
    assert 'pytest.skip: `skip_test("reason")`, from plain.test.' in message


def test_what_replaces_pytest_is_said_once_for_every_file_that_imports_it():
    root = write_tests(
        {
            "test_a.py": (
                "import pytest\n\ndef test_a():\n    pytest.raises(ValueError)\n"
            ),
            "test_b.py": ("import pytest\n\ndef test_b():\n    pytest.skip('no')\n"),
            "test_c.py": "import pytest\n",
        }
    )
    _, errors = collect_tests(["."], root=root)
    assert [error.path.name for error in errors] == [
        "test_a.py",
        "test_b.py",
        "test_c.py",
    ]
    first, second, third = (str(error.error) for error in errors)

    # The first says what replaces everything any of them uses.
    assert "pytest isn't used here" in first
    assert "What replaces what these files use:" in first
    assert "pytest.raises: `raises`" in first
    assert "pytest.skip: `skip_test" in first

    assert second == (
        "line 1: `import pytest`\n"
        "It uses pytest.skip. What replaces pytest is in the error for test_a.py."
    )
    assert third == (
        "line 1: `import pytest`\nWhat replaces pytest is in the error for test_a.py."
    )
    assert all(type(error.error) is TestDefinitionError for error in errors)


def test_a_helper_module_that_imports_pytest_is_named():
    root = write_tests(
        {
            "helpers_importing_pytest.py": (
                "import os\nimport pytest\n\ndef make_user():\n    return 'a user'\n"
            ),
            "test_uses_helper.py": (
                "from helpers_importing_pytest import make_user\n"
                "\n"
                "def test_user():\n"
                "    assert make_user()\n"
            ),
        }
    )
    with import_modules_from(root):
        tests, errors = collect_tests(["test_uses_helper.py"], root=root)
    assert tests == []
    assert type(errors[0].error) is TestDefinitionError
    message = str(errors[0].error)
    assert "helpers_importing_pytest.py, line 2: `import pytest`" in message
    assert "pytest isn't used here" in message
    assert "Traceback" not in message


def test_why_a_helper_is_imported_by_its_bare_name_is_said_once():
    root = write_tests(
        {
            "tests/helpers.py": "value = 1\n",
            "tests/test_a_imports.py": "from tests.helpers import value\n",
            "tests/test_b_imports.py": "from .helpers import value\n",
        }
    )
    _, errors = collect_tests(["."], root=root, helper_directory=root / "tests")
    first, second = (str(error.error) for error in errors)
    assert "should be `from helpers import value`" in first
    assert "A helper module is imported by its bare name" in first
    assert second == (
        "These imports can't be used in a test file:\n"
        "\n"
        "  line 1: `from .helpers import value` should be "
        "`from helpers import value`"
    )
    assert all(type(error.error) is TestDefinitionError for error in errors)


def test_an_import_from_a_conftest_is_not_told_to_import_the_conftest():
    root = write_tests(
        {
            "tests/conftest.py": "def make_user():\n    return 'a user'\n",
            "tests/test_a_from_conftest.py": (
                "from tests.conftest import make_user\n"
                "from .conftest import make_user as again\n"
                "from conftest import make_user as a_third_time\n"
                "import conftest\n"
            ),
        }
    )
    _, errors = collect_tests(["."], root=root, helper_directory=root / "tests")
    message = str(errors[1].error)
    for line in (1, 2, 3):
        assert f"line {line}: `from " in message
    assert "line 4: `import conftest` imports from a conftest.py" in message
    assert message.count("Import `make_user` from the helper module it moves to") == 3
    assert "should be" not in message
