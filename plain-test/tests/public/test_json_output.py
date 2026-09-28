"""
`plain test --json`: one document on stdout when the run is over, with
everything the text report says as data.

Each test runs the command on a project made for it.
"""

import json
import re
from pathlib import Path
from typing import Any

import plain.test
from plain.test import cases
from plain_test_helpers import CommandResult, run_in_project

ORDERS = (
    "from plain.test import skip, tag\n"
    "\n"
    "\n"
    "def price(items):\n"
    "    print(f'pricing {len(items)} items')\n"
    "    return {\n"
    "        'items': items,\n"
    "        'currency': 'USD',\n"
    "        'subtotal': 40,\n"
    "        'shipping': 0,\n"
    "        'total': 40,\n"
    "    }\n"
    "\n"
    "\n"
    "@tag('checkout')\n"
    "def test_order_total():\n"
    "    items = ['tea', 'kettle']\n"
    "    order = price(items)\n"
    "    assert order == {\n"
    "        'items': ['tea', 'kettle'],\n"
    "        'currency': 'USD',\n"
    "        'subtotal': 40,\n"
    "        'shipping': 2,\n"
    "        'total': 42,\n"
    "    }\n"
    "\n"
    "\n"
    "@skip('Waiting on the new billing API')\n"
    "def test_refund():\n"
    "    pass\n"
    "\n"
    "\n"
    "def test_empty_order():\n"
    "    assert price([])['total'] == 40\n"
)

ORDERS_PROJECT = {
    "tests/test_orders.py": ORDERS,
    "tests/test_invoices.py": "from billing_helpers import create_invoice\n",
}

INTERRUPTED_PROJECT = {
    "tests/test_sync.py": (
        "def test_every_page():\n"
        "    print('fetching page 1')\n"
        "    raise KeyboardInterrupt\n"
        "\n"
        "\n"
        "def test_after():\n"
        "    pass\n"
    )
}

STOPPED_PROJECT = {
    "tests/lifecycle.py": (
        "print('loading the lifecycle')\n\n\nclass AppTestLifecycle:\n    pass\n"
    ),
    "tests/test_one.py": "def test_one():\n    pass\n",
}

TEARDOWN_PROJECT = {
    "tests/lifecycle.py": (
        "from plain.test import TestLifecycle\n"
        "\n"
        "\n"
        "class AppTestLifecycle(TestLifecycle):\n"
        "    def teardown_worker(self):\n"
        "        print('dropping the database')\n"
        "        raise RuntimeError('still in use')\n"
    ),
    "tests/test_one.py": "def test_one():\n    pass\n",
}


def document_of(result: CommandResult) -> dict[str, Any]:
    """The document a run printed. It is all of stdout, or this raises."""
    return json.loads(result.stdout)


def run_as_json(files: dict[str, str], *arguments: str) -> dict[str, Any]:
    return document_of(run_in_project(files, "--json", *arguments))


def test_a_passing_run_prints_the_document_and_nothing_else():
    result = run_in_project(
        {
            "tests/test_it.py": (
                "import sys\n"
                "\n"
                "def test_writes():\n"
                "    print('to stdout')\n"
                "    print('to stderr', file=sys.stderr)\n"
            )
        },
        "--json",
    )
    assert result.exit_code == 0
    assert result.stderr == ""

    document = document_of(result)
    assert document["version"] == 1
    assert document["outcome"] == "passed"
    assert document["exit_code"] == 0
    assert document["counts"] == {
        "selected": 1,
        "passed": 1,
        "failed": 0,
        "skipped": 0,
        "not_run": 0,
        "collection_errors": 0,
    }
    # Counted, not listed.
    assert document["tests_listed"] == "failed_and_skipped"
    assert document["tests"] == []


def test_a_failure_says_where_without_anything_being_read_out_of_a_string():
    document = run_as_json(ORDERS_PROJECT)
    assert document["outcome"] == "failed"
    assert document["exit_code"] == 1

    test = document["tests"][0]
    assert test["id"] == "tests/test_orders.py::test_order_total"
    assert test["name"] == "test_order_total"
    assert test["tags"] == ["checkout"]
    assert test["outcome"] == "failed"
    # Where the test is defined, from its first decorator.
    assert (test["file"], test["line"]) == ("tests/test_orders.py", 15)

    failure = test["failure"]
    # The statement that failed.
    assert (failure["file"], failure["line"]) == ("tests/test_orders.py", 19)
    assert failure["frames"] == [
        {"file": "tests/test_orders.py", "line": 19, "function": "test_order_total"}
    ]
    assert failure["error_type"] == "AssertionError"
    assert failure["rerun_command"] == (
        "plain test tests/test_orders.py::test_order_total"
    )


def test_a_failure_carries_what_the_text_report_prints_as_data():
    failure = run_as_json(ORDERS_PROJECT)["tests"][0]["failure"]

    failed_assert = failure["assert"]
    assert failed_assert["expression"].startswith("order == {")
    assert failed_assert["message"] is None
    assert failed_assert["parts"] == [
        {
            "source": "order",
            "depth": 0,
            "evaluated": True,
            "value": {"text": "<dict with 5 keys>", "cut_characters": 0},
        }
    ]
    assert "- 'shipping': 0," in failed_assert["diff"]["lines"]
    assert "+ 'shipping': 2," in failed_assert["diff"]["lines"]
    assert failed_assert["diff"]["cut_lines"] == 0

    assert failure["locals"] == [
        {"name": "items", "value": {"text": "['tea', 'kettle']", "cut_characters": 0}}
    ]
    assert failure["stdout"] == {"text": "pricing 2 items\n", "cut_characters": 0}
    assert failure["stderr"] == {"text": "", "cut_characters": 0}
    assert "line 19, in test_order_total" in failure["traceback"]


def test_a_failure_raised_below_the_test_has_the_tests_line_and_every_frame():
    document = run_as_json(
        {
            "tests/shop.py": (
                "def charge(amount):\n    raise ValueError(f'cannot charge {amount}')\n"
            ),
            "tests/test_it.py": (
                "from shop import charge\n\n\ndef test_charge():\n    charge(-1)\n"
            ),
        }
    )
    failure = document["tests"][0]["failure"]
    assert failure["error_type"] == "ValueError"
    assert failure["error_message"] == "cannot charge -1"
    assert failure["assert"] is None
    # The line in the test, and then where it went.
    assert (failure["file"], failure["line"]) == ("tests/test_it.py", 5)
    assert failure["frames"] == [
        {"file": "tests/test_it.py", "line": 5, "function": "test_charge"},
        {"file": "tests/shop.py", "line": 2, "function": "charge"},
    ]


def test_a_part_that_was_never_evaluated_says_so():
    document = run_as_json(
        {
            "tests/test_it.py": (
                "def test_both():\n    rows = []\n    assert rows and rows[0] == 1\n"
            )
        }
    )
    parts = document["tests"][0]["failure"]["assert"]["parts"]
    assert parts == [
        {
            "source": "rows",
            "depth": 0,
            "evaluated": True,
            "value": {"text": "[]", "cut_characters": 0},
        },
        {"source": "rows[0] == 1", "depth": 0, "evaluated": False, "value": None},
    ]


def test_a_skipped_test_is_listed_with_its_reason():
    skipped = run_as_json(ORDERS_PROJECT)["tests"][1]
    assert skipped["id"] == "tests/test_orders.py::test_refund"
    assert skipped["outcome"] == "skipped"
    assert skipped["skip_reason"] == "Waiting on the new billing API"
    assert skipped["failure"] is None


def test_list_passed_lists_the_tests_that_passed_too():
    document = run_as_json(ORDERS_PROJECT, "--list-passed")
    assert document["tests_listed"] == "all"
    assert [(test["name"], test["outcome"]) for test in document["tests"]] == [
        ("test_order_total", "failed"),
        ("test_refund", "skipped"),
        ("test_empty_order", "passed"),
    ]


def test_every_test_has_the_same_fields_whatever_came_of_it():
    tests = run_as_json(ORDERS_PROJECT, "--list-passed")["tests"]
    assert len({tuple(test) for test in tests}) == 1
    # And a field that is a list or a number for one test is for all.
    for test in tests:
        assert type(test["tags"]) is list
        assert type(test["duration"]) is float
        assert type(test["line"]) is int


def test_a_file_that_could_not_be_collected_is_in_the_document():
    document = run_as_json(
        {
            **ORDERS_PROJECT,
            "tests/test_signup.py": "def test_signup(db, client):\n    pass\n",
        }
    )
    assert document["counts"]["collection_errors"] == 2

    by_file = {error["file"]: error for error in document["collection_errors"]}

    raised = by_file["tests/test_invoices.py"]
    assert raised["is_definition_error"] is False
    assert raised["error_type"] == "ModuleNotFoundError"
    assert raised["message"] == "No module named 'billing_helpers'"
    assert raised["line"] == 1
    assert "line 1, in <module>" in raised["traceback"]

    written_wrongly = by_file["tests/test_signup.py"]
    assert written_wrongly["is_definition_error"] is True
    assert written_wrongly["error_type"] == "TestDefinitionError"
    assert "There are no fixtures" in written_wrongly["message"]
    assert written_wrongly["traceback"] is None


def test_a_run_that_could_not_start_prints_a_document_too():
    result = run_in_project(STOPPED_PROJECT, "--json")
    assert result.exit_code == 2
    assert result.stderr == ""

    document = document_of(result)
    assert document["outcome"] == "stopped"
    assert document["exit_code"] == 2
    assert document["tests"] == []
    assert document["stopped"]["reason"] == "lifecycle_error"
    assert "doesn't define a TestLifecycle subclass" in document["stopped"]["message"]
    assert document["stopped"]["stdout"]["text"] == "loading the lifecycle\n"


@cases(
    (("tests/nope.py",), "target_not_found", 2),
    (("-k", "nothing_is_called_this"), "no_tests_found", 5),
)
def test_a_run_with_nothing_to_run_says_why(arguments, reason, exit_code):
    result = run_in_project(
        {"tests/test_one.py": "def test_one():\n    pass\n"}, "--json", *arguments
    )
    assert result.exit_code == exit_code
    document = document_of(result)
    assert document["exit_code"] == exit_code
    assert document["stopped"]["reason"] == reason


def test_a_run_stopped_with_ctrl_c_prints_its_document():
    result = run_in_project(INTERRUPTED_PROJECT, "--json")
    assert result.exit_code == 130

    document = document_of(result)
    assert document["outcome"] == "interrupted"
    assert document["counts"]["not_run"] == 2
    assert document["interrupted"] == {
        "id": "tests/test_sync.py::test_every_page",
        "file": "tests/test_sync.py",
        "line": 1,
        "stdout": {"text": "fetching page 1\n", "cut_characters": 0},
        "stderr": {"text": "", "cut_characters": 0},
    }


def test_a_lifecycle_that_fails_being_taken_down_is_in_the_document():
    document = run_as_json(TEARDOWN_PROJECT)
    assert document["outcome"] == "passed"
    (error,) = document["teardown_errors"]
    assert error["traceback"].endswith("RuntimeError: still in use\n")
    assert error["stdout"]["text"] == "dropping the database\n"


def test_the_document_says_what_was_asked_for():
    document = run_as_json(
        {
            "tests/test_orders.py": ORDERS,
            "tests/test_other.py": "def test_other():\n    assert False\n",
        },
        "tests/test_orders.py",
        "-k",
        "order",
        "--tag",
        "checkout",
        "--exclude-tag",
        "slow",
        "-x",
        "--full-values",
    )
    command = document["command"]
    assert command["targets"] == ["tests/test_orders.py"]
    assert command["keyword"] == "order"
    assert command["tags"] == ["checkout"]
    assert command["exclude_tags"] == ["slow"]
    assert command["fail_fast"] is True
    assert command["full_values"] is True
    assert command["argv"][-1] == "--full-values"
    assert Path(command["directory"], "tests/test_orders.py").is_file()

    # The one test the target, the keyword and the tag left.
    assert document["counts"]["selected"] == 1
    assert [test["name"] for test in document["tests"]] == ["test_order_total"]


def test_tests_after_the_first_failure_are_counted_as_not_run():
    document = run_as_json(
        {
            "tests/test_it.py": (
                "def test_a():\n    assert False\n\n"
                "def test_b():\n    pass\n\n"
                "def test_c():\n    pass\n"
            )
        },
        "-x",
    )
    assert document["counts"]["failed"] == 1
    assert document["counts"]["not_run"] == 2


def test_full_values_is_the_documents_too():
    prints_a_lot = (
        "def test_long():\n"
        "    text = 'x' * 5_000\n"
        "    print('y' * 20_000)\n"
        "    assert text.startswith('y')\n"
    )
    capped = run_as_json({"tests/test_it.py": prints_a_lot})
    failure = capped["tests"][0]["failure"]
    assert failure["stdout"]["cut_characters"] == 10_001
    text_value = failure["assert"]["parts"][1]["value"]
    assert text_value["cut_characters"] > 0

    whole = run_as_json({"tests/test_it.py": prints_a_lot}, "--full-values")
    failure = whole["tests"][0]["failure"]
    assert failure["stdout"] == {"text": "y" * 20_000 + "\n", "cut_characters": 0}
    text_value = failure["assert"]["parts"][1]["value"]
    assert text_value == {"text": repr("x" * 5_000), "cut_characters": 0}


@cases(
    (("--json", "-v"), "-v has"),
    (("--json", "--show-output"), "--show-output"),
    (("--json", "-s"), "--show-output"),
    (("--list-passed",), "--list-passed says what goes in the --json document"),
)
def test_flags_that_cannot_go_together_say_so(arguments, message):
    result = run_in_project(
        {"tests/test_one.py": "def test_one():\n    pass\n"}, *arguments
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert message in result.stderr


def shape(value: object) -> Any:
    """
    A value with what it holds taken out: the fields an object has and
    the kind of thing each is. A list is the shape of what is in it.
    """
    if isinstance(value, dict):
        return {key: shape(item) for key, item in value.items()}
    if isinstance(value, list):
        merged = "nothing"
        for item in value:
            merged = both(merged, shape(item))
        return [merged]
    if value is None:
        return "nothing"
    return type(value).__name__


def both(one: Any, other: Any) -> Any:
    """
    The shape of two values of the same kind. A field that is null in one
    and something in the other is that something: null is what a field
    with nothing to say holds.
    """
    if one == "nothing":
        return other
    if other == "nothing":
        return one
    if isinstance(one, dict) and isinstance(other, dict):
        assert set(one) == set(other), (sorted(one), sorted(other))
        return {key: both(one[key], other[key]) for key in one}
    if isinstance(one, list) and isinstance(other, list):
        return [both(one[0], other[0])]
    assert one == other, (one, other)
    return one


def test_the_readme_documents_the_document():
    readme = (Path(plain.test.__file__).parent / "README.md").read_text()
    section = readme.partition("\n### As JSON\n")[2].partition("\n## ")[0]
    examples = [
        json.loads(block)
        for block in re.findall(r"```json\n(.*?)```", section, re.DOTALL)
    ]
    whole_document, *parts = examples
    assert [list(part) for part in parts] == [
        ["interrupted"],
        ["stopped"],
        ["teardown_errors"],
    ]

    documented = shape(whole_document)
    for part in parts:
        (field,) = part
        documented[field] = both(documented[field], shape(part[field]))

    printed = shape(run_as_json(ORDERS_PROJECT))
    for project in (INTERRUPTED_PROJECT, STOPPED_PROJECT, TEARDOWN_PROJECT):
        printed = both(printed, shape(run_as_json(project)))

    assert documented == printed
