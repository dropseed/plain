import sys
import tempfile
from pathlib import Path

from plain.test import TestDefinitionError, patch, raises
from plain.test.runner import problems
from plain.test.runner.collection import collect_tests
from plain.test.runner.execution import run_tests
from plain.test.runner.reporting import collection_error_text
from plain.test.runner.targets import TargetError


def write_tests(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    return root


def test_collects_the_functions_named_for_it():
    root = write_tests(
        {
            "test_things.py": (
                "import dataclasses\n"
                "\n"
                "def make_thing():\n"
                "    return Thing(name='a thing')\n"
                "\n"
                "@dataclasses.dataclass\n"
                "class Thing:\n"
                "    name: str\n"
                "\n"
                "    def check(self):\n"
                "        return True\n"
                "\n"
                "class TestHelperlike:\n"
                "    pass\n"
                "\n"
                "def test_one():\n"
                "    assert make_thing().check()\n"
                "\n"
                "async def test_two():\n"
                "    assert True\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == [
        "test_things.py::test_one",
        "test_things.py::test_two",
    ]
    assert errors == []


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
    with raises(TargetError, match="No such test target: test_nope.py"):
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
            "test_parameters.py": (
                "def test_signup(user, client):\n"
                "    assert True\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
                "\n"
                "async def test_async(settings):\n"
                "    assert True\n"
            ),
            "test_other.py": "def test_ok():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)

    # The rest of the run is untouched; the file with the problem runs nothing.
    assert [t.id for t in tests] == ["test_other.py::test_ok"]
    assert len(errors) == 1
    assert errors[0].path.name == "test_parameters.py"

    error = errors[0].error
    assert isinstance(error, TestDefinitionError)
    message = str(error)
    # Every test that needs the fix is named, with the parameters in question.
    assert "test_signup(user, client) takes parameters" in message
    assert "test_async(settings) takes parameters" in message
    assert "test_fine" not in message
    assert "Nothing is passed to a test by name" in message
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
                "@cases(1, 2)\n"
                "def test_one_value(value):\n"
                "    assert value\n"
            )
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    assert "test_add(a, b) doesn't fit its @cases" in message
    assert "case [too many] passes 3 values, and the test takes 2: a and b." in message
    # Its first case fits, and so does every case of the other test.
    assert "case [1-2]" not in message
    assert "test_one_value" not in message


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
    message = str(errors[0].error)
    assert "line 5: test_pairs has 2 @cases. A test takes one." in message
    assert "@cases(*[(a, b, c) for a in FIRST for b, c in SECOND])" in message


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
    assert 'line 6: @skip requires a reason: @skip("why")' in str(errors[0].error)


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


def test_a_file_that_isnt_a_test_file_is_left_alone_whatever_it_is_called():
    """The runner knows one kind of file, `test_*.py`. Nothing else is read,
    run or reported, whatever another runner would have made of it."""
    root = write_tests(
        {
            "conftest.py": "import a_module_that_is_not_installed\n",
            "accounts/conftest.py": "raise RuntimeError('this file was run')\n",
            "accounts/__init__.py": "raise RuntimeError('this file was run')\n",
            "accounts/helpers.py": "raise RuntimeError('this file was run')\n",
            "accounts/test_users.py": "def test_user():\n    assert True\n",
        }
    )
    for target in (".", "accounts", "accounts/test_users.py"):
        tests, errors = collect_tests([target], root=root)
        assert [t.id for t in tests] == ["accounts/test_users.py::test_user"]
        assert errors == []


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
    for name in ("test_sync", "test_async", "test_wrapped"):
        assert f"{name}() has a `yield` in it" in message
    assert "test_fine" not in message
    # What to write, for a test that yielded values and for one that
    # yielded between setup and cleanup.
    assert "@cases(...)" in message
    assert "`@contextmanager`" in message


def classes_are_refused():
    """As the runner is meant to be: a class with tests in it isn't run."""
    # CLASSES AS TESTS: this function, and every `with` that enters it.
    return patch(problems, "TEST_CLASSES_ARE_COLLECTED", False)


def test_a_class_with_tests_in_it_is_a_collection_error():
    root = write_tests(
        {
            "test_classes.py": (
                "import unittest\n"
                "\n"
                "class TestCheckout:\n"
                "    def test_requires_login(self):\n"
                "        assert False\n"
                "\n"
                "    @staticmethod\n"
                "    def test_static():\n"
                "        assert False\n"
                "\n"
                "    @classmethod\n"
                "    def test_class(cls):\n"
                "        assert False\n"
                "\n"
                "    def helper(self):\n"
                "        pass\n"
                "\n"
                "class UserTests(unittest.TestCase):\n"
                "    def test_it(self):\n"
                "        self.assertEqual(1, 2)\n"
                "\n"
                "class TestHelperlike:\n"
                "    def check(self):\n"
                "        pass\n"
                "\n"
                "def test_fine():\n"
                "    assert True\n"
            ),
            "test_other.py": "def test_ok():\n    assert True\n",
        }
    )
    with classes_are_refused():
        tests, errors = collect_tests(["."], root=root)

    assert [t.id for t in tests] == ["test_other.py::test_ok"]
    assert len(errors) == 1
    assert type(errors[0].error) is TestDefinitionError
    assert str(errors[0].error) == (
        "These tests can't be run as written:\n"
        "\n"
        "  line 3: TestCheckout is a class with 3 tests in it.\n"
        "  line 18: UserTests is a class with 1 test in it.\n"
        "\n"
        "A test is a function, and a file is the group. Write each of the\n"
        "class's tests as a function of the file, and what they shared as\n"
        "functions they call. A class that isn't a test, and has to have a\n"
        "method named `test_*`, belongs in a helper module."
    )


def test_a_class_that_was_imported_is_someone_elses_class():
    root = write_tests(
        {
            "fakes_shared_by_collection_tests.py": (
                "class FakeBackend:\n"
                "    def test_connection(self):\n"
                "        return 'not a test: the app calls this'\n"
            ),
            "test_uses_the_fake.py": (
                "from fakes_shared_by_collection_tests import FakeBackend\n"
                "\n"
                "def test_backend():\n"
                "    assert FakeBackend().test_connection()\n"
            ),
        }
    )
    with import_modules_from(root), classes_are_refused():
        tests, errors = collect_tests(["test_uses_the_fake.py"], root=root)
    assert errors == []
    assert [t.name for t in tests] == ["test_backend"]


def test_a_class_is_not_something_a_target_can_name():
    root = write_tests(
        {
            "test_target.py": (
                "def test_one():\n"
                "    assert True\n"
                "\n"
                "@cases(1, 2)\n"
                "def test_many(number):\n"
                "    assert number\n"
            ).replace("@cases", "from plain.test import cases\n\n@cases", 1)
        }
    )
    with classes_are_refused():
        tests, _ = collect_tests(["test_target.py::test_many"], root=root)
        assert [t.name for t in tests] == ["test_many[1]", "test_many[2]"]
        tests, _ = collect_tests(["test_target.py::test"], root=root)
        assert tests == []


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
            ),
            "test_imports.py": (
                "from checks_shared_by_collection_tests import (\n"
                "    test_connection as check_connection,\n"
                "    test_shared,\n"
                ")\n"
                "\n"
                "def test_own():\n"
                "    assert check_connection()\n"
            ),
        }
    )
    with import_modules_from(root):
        tests, errors = collect_tests(["test_imports.py"], root=root)
    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    listed = message.split("\n\n")[1]
    # One imported under another name is not a test, and is not listed.
    assert listed == (
        "  test_shared is defined in checks_shared_by_collection_tests, "
        "not in this file."
    )
    assert "A test is run by the file that defines it" in message


def test_a_file_with_many_tests_to_fix_says_how_many_and_not_which():
    tests_asking = "".join(
        f"def test_number_{number}(user, org):\n    assert True\n\n"
        for number in range(12)
    )
    root = write_tests(
        {"test_many.py": tests_asking + "def test_other(org, limit=3):\n    pass\n"}
    )
    _, errors = collect_tests(["."], root=root)
    assert str(errors[0].error) == (
        "These tests can't be run as written:\n"
        "\n"
        "  13 tests take parameters, and nothing passes them in.\n"
        "\n"
        # One with a default is not something to fix.
        "  user  12 tests\n"
        "  org   13 tests\n"
        "\n"
        "Nothing is passed to a test by name. A test gets what it needs in its\n"
        "body, by calling a helper or entering a `with` block, and takes values\n"
        "only from @cases(...)."
    )


def test_what_a_test_takes_is_said_once():
    root = write_tests(
        {
            "test_a.py": "def test_a(user):\n    assert True\n",
            "test_b.py": "def test_b(user):\n    assert True\n",
            "test_c.py": "def test_c(user):\n    assert True\n",
        }
    )
    _, errors = collect_tests(["."], root=root)
    messages = [str(error.error) for error in errors]
    said = [
        message.count("Nothing is passed to a test by name") for message in messages
    ]
    assert said == [1, 0, 0]
    for message in messages[1:]:
        assert "test_b(user) takes" in message or "test_c(user) takes" in message
        assert "What to write instead is in the error for test_a.py." in message
    # Each is still the one kind of error there is.
    assert all(type(error.error) is TestDefinitionError for error in errors)


def test_a_module_that_isnt_installed_is_an_import_error_like_any_other():
    """The runner knows nothing of other runners. A file written for one
    imports a module that isn't there, which is what the file is told."""
    root = write_tests(
        {
            "test_written_for_another_runner.py": (
                "import pytest\n"
                "\n"
                "@pytest.mark.parametrize('n', [1, 2])\n"
                "def test_numbers(n, tmp_path):\n"
                "    with pytest.raises(ValueError):\n"
                "        int('x')\n"
            ),
            "test_fine.py": "def test_fine():\n    assert True\n",
        }
    )
    tests, errors = collect_tests(["."], root=root)
    assert [t.id for t in tests] == ["test_fine.py::test_fine"]
    assert len(errors) == 1
    assert type(errors[0].error) is ModuleNotFoundError

    text = collection_error_text(errors[0].error)
    lines = text.splitlines()
    assert lines[0] == "Traceback (most recent call last):"
    assert ", line 1, in <module>" in lines[1]
    assert lines[-1] == "ModuleNotFoundError: No module named 'pytest'"
    assert "plain.test" not in text


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


def test_a_helper_module_is_a_helper_module_whatever_it_is_called():
    root = write_tests(
        {
            "tests/conftest.py": "def make_user():\n    return 'a user'\n",
            "tests/test_a.py": (
                "from conftest import make_user\n"
                "\n"
                "def test_user():\n"
                "    assert make_user() == 'a user'\n"
            ),
            "tests/test_b.py": "from tests.conftest import make_user\n",
        }
    )
    with import_modules_from(root / "tests"):
        tests, errors = collect_tests(["."], root=root, helper_directory=root / "tests")
    assert [t.id for t in tests] == ["tests/test_a.py::test_user"]
    assert "should be `from conftest import make_user`" in str(errors[0].error)


def test_a_case_that_passes_too_few_names_what_it_fills_and_what_it_doesnt():
    root = write_tests(
        {
            "test_fit.py": (
                "from plain.test import case, cases\n"
                "\n"
                "\n"
                '@cases(case("annual", 500, id="annual"), case("monthly", id="monthly"))\n'
                "def test_price(plan, amount, currency):\n"
                "    pass\n"
            )
        }
    )

    _, errors = collect_tests(["."], root=root)

    message = str(errors[0].error)
    assert (
        "test_price(plan, amount, currency) doesn't fit its @cases: "
        "case [annual] passes 2 values, for plan and amount. "
        "Nothing fills currency."
    ) in message
    assert (
        "case [monthly] passes 1 value, for plan. Nothing fills amount and currency."
    ) in message


def test_a_file_says_everything_wrong_with_it_at_once():
    """It imports a helper the wrong way, its tests take parameters, one
    has two `@cases`, one yields and one is in a class. Found one at a
    time, that is five runs."""
    root = write_tests(
        {
            "tests/helpers.py": "value = 1\n",
            "tests/test_orders.py": (
                "from plain.test import cases\n"
                "from tests.helpers import value\n"
                "\n"
                "\n"
                "def test_total(order):\n"
                "    assert order.total == 5\n"
                "\n"
                "\n"
                '@cases("monthly", "annual")\n'
                '@cases((5, "usd"))\n'
                "def test_price(plan, amount, currency):\n"
                "    pass\n"
                "\n"
                "\n"
                "def test_steps():\n"
                "    yield 1\n"
                "\n"
                "\n"
                "class TestRefunds:\n"
                "    def test_refund(self):\n"
                "        pass\n"
            ),
        }
    )

    with classes_are_refused():
        tests, errors = collect_tests(["."], root=root, helper_directory=root / "tests")

    assert tests == []
    assert len(errors) == 1
    message = str(errors[0].error)
    assert "line 19: TestRefunds is a class with 1 test in it." in message
    assert (
        "line 2: `from tests.helpers import value` should be "
        "`from helpers import value`"
    ) in message
    assert "test_total(order) takes parameters" in message
    assert "order  1 test" in message
    assert "line 11: test_price has 2 @cases. A test takes one." in message
    assert "test_steps() has a `yield` in it." in message


def test_every_decorator_that_would_raise_is_reported_not_the_first():
    root = write_tests(
        {
            "test_decorated.py": (
                "from plain.test import cases, skip, tag\n"
                "\n"
                "\n"
                "@cases(1, 2)\n"
                "@cases(3, 4)\n"
                "def test_first(a, b):\n"
                "    pass\n"
                "\n"
                "\n"
                "@skip\n"
                "def test_second():\n"
                "    pass\n"
                "\n"
                "\n"
                "@tag\n"
                "def test_third():\n"
                "    pass\n"
                "\n"
                "\n"
                "def test_fourth(user):\n"
                "    pass\n"
            )
        }
    )

    _, errors = collect_tests(["."], root=root)

    assert len(errors) == 1
    message = str(errors[0].error)
    assert "line 6: test_first has 2 @cases. A test takes one." in message
    assert 'line 10: @skip requires a reason: @skip("why")' in message
    assert 'line 15: @tag requires at least one name: @tag("slow")' in message
    assert "test_fourth(user) takes parameters" in message


def test_a_decorator_the_reader_doesnt_know_may_pass_the_parameters():
    """Reading reports what is certain. `mock.patch` passes the test a
    mock, so its parameter isn't one that nothing fills."""
    root = write_tests(
        {
            "tests/helpers.py": "value = 1\n",
            "tests/test_patched.py": (
                "from unittest import mock\n"
                "\n"
                # What makes this a file that is read, not run.
                "from tests.helpers import value\n"
                "\n"
                "\n"
                '@mock.patch("os.getcwd")\n'
                "def test_patched(getcwd):\n"
                "    pass\n"
            ),
        }
    )

    _, errors = collect_tests(["."], root=root, helper_directory=root / "tests")

    message = str(errors[0].error)
    assert "line 3: `from tests.helpers import value`" in message
    assert "takes parameters" not in message


_A_TEST = "def test_one():\n    assert True\n"


def test_a_tests_directory_is_not_imported_as_a_package():
    root = write_tests(
        {
            "tests/__init__.py": "raise RuntimeError('this file was run')\n",
            "tests/test_first.py": _A_TEST,
        }
    )

    tests, errors = collect_tests(["."], root=root, helper_directory=root / "tests")

    assert [test.id for test in tests] == ["tests/test_first.py::test_one"]
    assert errors == []
