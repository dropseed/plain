import tempfile
from pathlib import Path

from plain.test import TestDefinitionError, raises
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
