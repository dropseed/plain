"""
What a failed test prints: the values inside the assert, what differs
between two large values, and what else the test had in hand.

Each test runs the command on a project with one failing test in it.
"""

from plain.test import cases
from plain_test_helpers import block, run_in_project


def failing(
    test_source: str, *arguments: str, beside_it: dict[str, str] | None = None
) -> str:
    """What the command prints for a project whose one test file fails."""
    files = {"tests/test_it.py": test_source, **(beside_it or {})}
    result = run_in_project(files, *arguments)
    assert result.exit_code == 1, result.output
    return result.output


def test_an_attribute_is_shown_with_what_it_is_an_attribute_of():
    output = failing(
        "class Response:\n"
        "    status_code = 404\n"
        "    def __repr__(self):\n"
        "        return '<Response 404>'\n"
        "\n"
        "def test_found():\n"
        "    response = Response()\n"
        "    assert response.status_code == 200\n"
    )
    assert block(output, "assert ") == [
        "assert response.status_code == 200",
        "  response.status_code = 404",
        "    response = <Response 404>",
    ]


def test_a_call_is_shown_with_what_it_returned_and_what_it_was_given():
    output = failing(
        "def test_count():\n"
        "    rows = [{'id': 1}, {'id': 2}]\n"
        "    expected = 3\n"
        "    assert len(rows) == expected\n"
    )
    assert block(output, "assert ") == [
        "assert len(rows) == expected",
        "  len(rows) = 2",
        "    rows = [{'id': 1}, {'id': 2}]",
        "  expected = 3",
    ]


def test_a_membership_test_shows_both_sides():
    output = failing(
        "def sent_to(outbox):\n"
        "    return [message['to'] for message in outbox]\n"
        "\n"
        "def test_sent():\n"
        "    outbox = [{'to': 'a@example.com'}]\n"
        "    email = 'b@example.com'\n"
        "    assert email in sent_to(outbox)\n"
    )
    assert block(output, "assert ") == [
        "assert email in sent_to(outbox)",
        "  email = 'b@example.com'",
        "  sent_to(outbox) = ['a@example.com']",
        "    outbox = [{'to': 'a@example.com'}]",
    ]


def test_what_python_never_evaluated_is_said_to_be_not_evaluated():
    output = failing(
        "def explode():\n"
        "    raise RuntimeError('never called')\n"
        "\n"
        "def test_items():\n"
        "    items = []\n"
        "    assert items and explode()\n"
    )
    assert block(output, "assert ") == [
        "assert items and explode()",
        "  items = []",
        "  explode()  (not evaluated)",
    ]
    assert "RuntimeError" not in output


def test_what_is_inside_a_part_that_was_not_evaluated_is_not_listed():
    output = failing(
        "class User:\n"
        "    is_staff = False\n"
        "    name = 'ada'\n"
        "    def __repr__(self):\n"
        "        return '<User ada>'\n"
        "\n"
        "def test_staff():\n"
        "    user = User()\n"
        "    assert user.is_staff and user.name == 'grace'\n"
    )
    assert block(output, "assert ") == [
        "assert user.is_staff and user.name == 'grace'",
        "  user.is_staff = False",
        "    user = <User ada>",
        "  user.name == 'grace'  (not evaluated)",
    ]


def test_a_chained_comparison_shows_every_side_it_reached():
    output = failing(
        "def test_between():\n"
        "    low, value, high = 1, 12, 10\n"
        "    assert low < value < high\n"
    )
    assert block(output, "assert ") == [
        "assert low < value < high",
        "  low = 1",
        "  value = 12",
        "  high = 10",
    ]


def test_the_message_is_printed_once_where_python_prints_it():
    output = failing(
        "def test_total():\n"
        "    total = 41\n"
        "    assert total == 42, 'the total should include shipping'\n"
    )
    assert "AssertionError: the total should include shipping" in output
    assert output.count("the total should include shipping") == 2  # and the source
    assert block(output, "assert total") == [
        "assert total == 42",
        "  total = 41",
    ]


def test_small_values_are_printed_whole_and_not_diffed():
    output = failing(
        "def test_small():\n"
        "    result = {'a': 1, 'b': 2}\n"
        "    assert result == {'a': 1, 'b': 3}\n"
    )
    assert block(output, "assert ") == [
        "assert result == {'a': 1, 'b': 3}",
        "  result = {'a': 1, 'b': 2}",
    ]
    assert "diff:" not in output


def test_two_large_dicts_are_printed_as_the_keys_that_differ():
    output = failing(
        "def test_large():\n"
        "    result = {f'key_{n}': n for n in range(30)}\n"
        "    expected = dict(result, key_17='seventeen')\n"
        "    assert result == expected\n"
    )
    assert block(output, "assert ") == [
        "assert result == expected",
        "  result = <dict with 30 keys>",
        "  expected = <dict with 30 keys>",
    ]
    assert block(output, "diff:") == [
        "diff:",
        "  --- result",
        "  +++ expected",
        "  @@ -8,5 +8,5 @@",
        "    'key_15': 15,",
        "    'key_16': 16,",
        "  - 'key_17': 17,",
        "  + 'key_17': 'seventeen',",
        "    'key_18': 18,",
        "    'key_19': 19,",
    ]
    # Nothing prints the dicts whole: not the assert, and not the locals.
    assert "'key_3': 3" not in output


def test_two_lists_are_printed_as_the_items_that_differ():
    output = failing(
        "def test_rows():\n"
        "    rows = [f'row number {n}' for n in range(20)]\n"
        "    expected = [*rows[:9], 'another row', *rows[10:], 'one more']\n"
        "    assert rows == expected\n"
    )
    diff = block(output, "diff:")
    assert "  - 'row number 9'," in diff
    assert "  + 'another row'," in diff
    assert "  + 'one more']" in diff
    assert "    'row number 3'," not in diff


def test_text_is_compared_line_by_line():
    output = failing(
        "def test_letter():\n"
        "    letter = 'Dear A,\\n\\nIt ships Tuesday.\\n\\nThanks\\n'\n"
        "    assert letter == 'Dear A,\\n\\nIt ships Monday.\\n\\nThanks\\n'\n"
    )
    assert block(output, "assert ")[1] == "  letter = <str, 35 characters in 5 lines>"
    diff = block(output, "diff:")
    assert "  -It ships Tuesday." in diff
    assert "  +It ships Monday." in diff
    assert "   Thanks" in diff


def test_text_that_differs_only_in_what_cannot_be_seen_is_shown_by_its_repr():
    output = failing(
        "def test_endings():\n"
        "    written = 'first\\nsecond\\n'\n"
        "    assert written == 'first\\nsecond \\n'\n"
    )
    diff = block(output, "diff:")
    assert "  -'second\\n'" in diff
    assert "  +'second \\n'" in diff


def test_text_that_differs_in_how_it_ends_is_shown_by_its_repr():
    output = failing(
        "def test_endings():\n"
        "    written = 'first\\nsecond'\n"
        "    assert written == 'first\\nsecond\\n'\n"
    )
    diff = block(output, "diff:")
    assert "  -'second'" in diff
    assert "  +'second\\n'" in diff


def test_two_long_strings_on_one_line_are_shown_where_they_first_differ():
    output = failing(
        "def test_token():\n"
        "    left = 'x' * 300 + 'A' + 'y' * 300\n"
        "    right = 'x' * 300 + 'B' + 'y' * 300\n"
        "    assert left == right\n"
    )
    diff = block(output, "diff:")
    assert diff[1] == (
        "  first difference at character 300 (left is 601 characters, right is 601)"
    )
    assert diff[2] == f"  - ...'{'x' * 30}A{'y' * 49}'..."
    assert diff[3] == f"  + ...'{'x' * 30}B{'y' * 49}'..."


def test_two_dataclasses_are_compared_field_by_field():
    output = failing(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class Address:\n"
        "    street: str\n"
        "    city: str\n"
        "    postal_code: str\n"
        "    notes: str\n"
        "\n"
        "def test_address():\n"
        "    left = Address('1 Long Street Name Avenue', 'Springfield', '12345', 'at the door')\n"
        "    right = Address('1 Long Street Name Avenue', 'Shelbyville', '12345', 'at the door')\n"
        "    assert left == right\n"
    )
    diff = block(output, "diff:")
    assert "  -        city='Springfield'," in diff
    assert "  +        city='Shelbyville'," in diff


def test_a_failure_that_is_not_an_assert_prints_what_the_test_had():
    output = failing(
        "def test_setting():\n"
        "    settings = {'debug': True}\n"
        "    count = 3\n"
        "    assert settings['missing'] == count\n"
    )
    assert "KeyError: 'missing'" in output
    assert block(output, "locals:") == [
        "locals:",
        "  settings = {'debug': True}",
        "  count = 3",
    ]


def test_locals_are_the_test_functions_however_deep_the_failure():
    output = failing(
        "def check(order):\n"
        "    subtotal = 25\n"
        "    assert order['total'] == subtotal\n"
        "\n"
        "def test_order():\n"
        "    order = {'total': 30}\n"
        "    currency = 'USD'\n"
        "    check(order)\n"
    )
    # The assert is the helper's, with the helper's values.
    assert block(output, "assert ") == [
        "assert order['total'] == subtotal",
        "  order['total'] = 30",
        "    order = {'total': 30}",
        "  subtotal = 25",
    ]
    # The locals are the test's. `order` is already printed above.
    assert block(output, "locals:") == ["locals:", "  currency = 'USD'"]


def test_locals_leave_out_what_the_assert_printed_and_what_says_nothing():
    output = failing(
        "import json\n"
        "\n"
        "def test_names():\n"
        "    import os\n"
        "    from pathlib import Path\n"
        "    def helper():\n"
        "        pass\n"
        "    encode = json.dumps\n"
        "    first = 1\n"
        "    second = 2\n"
        "    assert first == 10\n"
    )
    assert block(output, "locals:") == ["locals:", "  second = 2"]


def test_a_test_in_a_class_and_a_case_of_a_test_have_their_locals():
    output = failing(
        "from plain.test import cases\n"
        "\n"
        "class TestPrices:\n"
        "    @cases(('annual', 100))\n"
        "    def test_price(self, plan, price):\n"
        "        discount = 10\n"
        "        raise ValueError('no price')\n"
    )
    found = block(output, "locals:")
    assert found[0] == "locals:"
    assert found[1].startswith("  self = <")
    assert found[2:] == ["  plan = 'annual'", "  price = 100", "  discount = 10"]


def test_an_async_test_has_its_values_and_its_locals():
    output = failing(
        "async def fetch(path):\n"
        "    return 404\n"
        "\n"
        "async def test_fetch():\n"
        "    path = '/missing'\n"
        "    retries = 2\n"
        "    assert await fetch(path) == 200\n"
    )
    assert block(output, "assert ") == [
        "assert await fetch(path) == 200",
        "  await fetch(path) = 404",
        "    path = '/missing'",
    ]
    assert block(output, "locals:") == ["locals:", "  retries = 2"]


def test_a_value_is_cut_at_the_cap_and_says_how_much_was_cut():
    output = failing(
        "def test_body():\n    body = 'x' * 10_000\n    assert 'needle' in body\n"
    )
    found = block(output, "assert ")
    assert found[0] == "assert 'needle' in body"
    # 10,000 characters and the two quotes, less the 2,000 that are printed.
    assert found[-1] == "    ... 8,002 more characters (--full-values prints them)"
    assert output.count("x") < 2_100


def test_full_values_prints_a_value_whole():
    output = failing(
        "def test_body():\n    body = 'x' * 10_000\n    assert 'needle' in body\n",
        "--full-values",
    )
    assert "more characters" not in output
    assert output.count("x") >= 10_000


def test_a_long_diff_is_cut_and_says_how_much_was_cut():
    source = (
        "def test_rows():\n"
        "    rows = [f'row number {n}' for n in range(200)]\n"
        "    expected = [f'ROW number {n}' for n in range(200)]\n"
        "    assert rows == expected\n"
    )
    diff = block(failing(source), "diff:")
    assert len(diff) == 1 + 60 + 1
    assert diff[-1] == "  ... 343 more lines (--full-values prints them)"

    whole = block(failing(source, "--full-values"), "diff:")
    assert len(whole) == 1 + 403


def test_a_repr_that_raises_is_reported_and_the_rest_is_printed():
    output = failing(
        "class Unprintable:\n"
        "    def __repr__(self):\n"
        "        raise ValueError('no repr')\n"
        "\n"
        "def test_thing():\n"
        "    thing = Unprintable()\n"
        "    things = [1, thing]\n"
        "    count = 2\n"
        "    assert thing is None\n"
    )
    assert block(output, "assert ") == [
        "assert thing is None",
        "  thing = <Unprintable: its repr raised ValueError: no repr>",
    ]
    assert block(output, "locals:") == [
        "locals:",
        "  things = [1, <Unprintable: its repr raised ValueError: no repr>]",
        "  count = 2",
    ]


def test_a_lifecycle_describes_the_values_it_owns():
    output = failing(
        "from orders import Order\n"
        "\n"
        "def test_order():\n"
        "    order = Order()\n"
        "    assert order is None\n",
        beside_it={
            "tests/orders.py": (
                "class Order:\n"
                "    total = 30\n"
                "    def __repr__(self):\n"
                "        return '<Order object>'\n"
            ),
            "tests/lifecycle.py": (
                "from orders import Order\n"
                "\n"
                "from plain.test import TestLifecycle\n"
                "\n"
                "class ProjectLifecycle(TestLifecycle):\n"
                "    def describe_value(self, value):\n"
                "        if isinstance(value, Order):\n"
                "            return f'Order(total={value.total})'\n"
                "        return None\n"
            ),
        },
    )
    assert block(output, "assert ") == [
        "assert order is None",
        "  order = Order(total=30)",
    ]


def test_a_describer_that_raises_leaves_the_value_to_its_repr():
    output = failing(
        "def test_total():\n    total = 41\n    assert total == 42\n",
        beside_it={
            "tests/lifecycle.py": (
                "from plain.test import TestLifecycle\n"
                "\n"
                "class ProjectLifecycle(TestLifecycle):\n"
                "    def describe_value(self, value):\n"
                "        raise RuntimeError('describing went wrong')\n"
            ),
        },
    )
    assert block(output, "assert ") == ["assert total == 42", "  total = 41"]
    assert "describing went wrong" not in output


def test_the_traceback_and_the_rerun_command_are_still_there():
    output = failing("def test_total():\n    total = 41\n    assert total == 42\n")
    assert "Traceback (most recent call last):" in output
    assert "line 3, in test_total" in output
    assert "Re-run: plain test tests/test_it.py::test_total" in output


HOLDS_SECRETS = (
    "import os\n"
    "\n"
    "os.environ['PAYMENTS_KEY'] = 'sk_live_FAKESECRET123'\n"
    "\n"
    "\n"
    "def test_environment():\n"
    "    for_a_subprocess = {**os.environ, 'DEBUG': '1'}\n"
    "    together = [('the environment', os.environ), for_a_subprocess]\n"
    "    assert 'PAYMENTS_KEY' not in os.environ\n"
)


@cases((), ("--full-values",), ("--json",), ("--json", "--full-values"))
def test_the_environment_is_printed_without_its_values(*arguments):
    output = failing(HOLDS_SECRETS, *arguments)
    assert "FAKESECRET" not in output
    # What is printed says that something was left out, and what.
    assert "values withheld" in output
    assert "PAYMENTS_KEY" in output
    assert "DEBUG" in output


def test_the_settings_are_printed_without_their_values():
    result = run_in_project(
        {
            "app/settings.py": (
                "SECRET_KEY = 'FAKESECRET-settings-key'\n"
                "URLS_ROUTER = 'app.urls.AppRouter'\n"
            ),
            "tests/test_it.py": (
                "from plain.runtime import settings\n"
                "\n"
                "\n"
                "def test_settings():\n"
                "    configured = settings\n"
                "    assert settings is None\n"
            ),
        },
        "--full-values",
    )
    assert result.exit_code == 1, result.output
    assert 'settings = <Settings "app.settings">' in result.output
    assert "FAKESECRET" not in result.output


def test_a_value_the_failure_has_twice_is_printed_once():
    output = failing(
        "def test_rows():\n"
        "    rows = [{'id': n, 'name': f'row number {n}'} for n in range(6)]\n"
        "    again = list(rows)\n"
        "    assert len(rows) == 7\n"
    )
    assert output.count("'name': 'row number 5'") == 1
    assert block(output, "locals:") == ["locals:", "  again = <the same as rows>"]
