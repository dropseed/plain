"""
Tests aren't kept in the application, and a test file that is there is not
passed over without a word.

`app/` is what is imported as `app` and what gets deployed, so tests live
beside it. A run that comes to a test file in it, or is given one as a
target, doesn't run it and says so: which files, and where they belong.
"""

import json

from plain.testing import cases
from plain_test_helpers import run_in_project, section

APPLICATION = {
    "app/settings.py": (
        'SECRET_KEY = "for the tests"\nURLS_ROUTER = "app.urls.AppRouter"\n'
    ),
    "app/urls.py": (
        "from plain.urls import Router\n"
        "\n"
        "\n"
        "class AppRouter(Router):\n"
        '    namespace = ""\n'
        "    urls = ()\n"
    ),
}

# It fails, and says so, if it is ever run.
A_TEST_IN_THE_APPLICATION = (
    "def test_in_the_application():\n"
    "    print('the test in the application ran')\n"
    "    assert False\n"
)

A_TEST_BESIDE_IT = "def test_beside_it():\n    pass\n"


def test_a_test_file_in_the_application_is_reported_and_not_run():
    result = run_in_project(
        {
            **APPLICATION,
            "app/billing/test_refunds.py": A_TEST_IN_THE_APPLICATION,
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        }
    )

    assert result.exit_code == 1
    assert "1 passed, 1 collection error in" in result.output
    assert "the test in the application ran" not in result.output

    said = section(result.output, "collection error app")
    assert "1 test file is in app/, and it was not run:" in said
    assert "    app/billing/test_refunds.py" in said
    assert "Tests live in tests/, beside app/." in said
    assert "Move it to tests/." in said


def test_a_suite_kept_in_the_application_is_not_no_tests_found():
    """It exits 1, not 4: `plain check` takes 4 to mean there is nothing to
    run, and a suite that wasn't run is not nothing."""
    result = run_in_project(
        {
            **APPLICATION,
            **{
                f"app/tests/test_{name}.py": A_TEST_IN_THE_APPLICATION
                for name in ("carts", "orders", "prices", "refunds")
            },
            "app/users/tests/test_signup.py": A_TEST_IN_THE_APPLICATION,
        }
    )

    assert result.exit_code == 1
    assert "No tests found" not in result.output
    assert "0 passed, 1 collection error in" in result.output
    assert "the test in the application ran" not in result.output

    said = section(result.output, "collection error app")
    assert "5 test files are in app/, and none of them was run:" in said
    assert "    app/tests        4 files" in said
    assert "    app/users/tests  1 file" in said
    assert "Move them to tests/." in said


@cases(
    "app/tests/test_inside.py",
    "app/tests/test_inside.py::test_in_the_application",
    "app/tests/test_inside.py:2",
    "app/tests",
    "app",
)
def test_a_target_in_the_application_is_refused_the_same_way(target):
    result = run_in_project(
        {
            **APPLICATION,
            "app/tests/test_inside.py": A_TEST_IN_THE_APPLICATION,
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        },
        target,
    )

    assert result.exit_code == 1
    assert "No tests found" not in result.output
    assert "the test in the application ran" not in result.output

    said = section(result.output, "collection error app")
    assert "1 test file is in app/, and it was not run:" in said
    assert "    app/tests/test_inside.py" in said


def test_a_target_beside_the_application_does_not_go_looking_in_it():
    result = run_in_project(
        {
            **APPLICATION,
            "app/tests/test_inside.py": A_TEST_IN_THE_APPLICATION,
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        },
        "tests",
    )

    assert result.exit_code == 0
    assert "collection error" not in result.output


def test_a_module_of_the_application_named_like_a_test_file_is_left_alone():
    """`app/test_connection.py` checks a connection. It defines no test, so
    it isn't one that was left out."""
    result = run_in_project(
        {
            **APPLICATION,
            "app/test_connection.py": "def check_connection():\n    return True\n",
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        }
    )

    assert result.exit_code == 0
    assert "collection error" not in result.output


def test_a_class_with_tests_in_the_application_is_a_test_file_too():
    result = run_in_project(
        {
            **APPLICATION,
            "app/tests/test_cart.py": (
                "class TestCart:\n    def test_empty(self):\n        assert False\n"
            ),
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        }
    )

    assert result.exit_code == 1
    assert "    app/tests/test_cart.py" in section(
        result.output, "collection error app"
    )


def test_only_the_application_is_left_out_not_every_directory_named_for_it():
    result = run_in_project(
        {
            **APPLICATION,
            "tests/mobile/app/test_screens.py": (
                "def test_the_first_screen():\n    pass\n"
            ),
        }
    )

    assert result.exit_code == 0
    assert "1 passed in" in result.output


def test_a_project_with_no_application_has_nowhere_tests_are_not_kept():
    result = run_in_project(
        {"app_checks/test_it.py": A_TEST_BESIDE_IT, "test_top.py": A_TEST_BESIDE_IT}
    )

    assert result.exit_code == 0
    assert "2 passed in" in result.output


def test_the_document_says_it_as_a_collection_error_of_the_application():
    result = run_in_project(
        {
            **APPLICATION,
            "app/tests/test_inside.py": A_TEST_IN_THE_APPLICATION,
            "tests/test_beside.py": A_TEST_BESIDE_IT,
        },
        "--json",
    )

    assert result.exit_code == 1
    document = json.loads(result.stdout)
    assert document["counts"]["passed"] == 1
    assert document["counts"]["collection_errors"] == 1

    error = document["collection_errors"][0]
    assert error["file"] == "app"
    assert error["is_definition_error"] is True
    assert "app/tests/test_inside.py" in error["message"]
