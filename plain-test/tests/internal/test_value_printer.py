"""
Printing a value for a failure report: what is known to be secret is left
out wherever the value is, and a large value is printed once.
"""

import os

from plain.test import patch
from plain.test.runner.printing import ValuePrinter

SECRET = "sk_live_FAKESECRET123"


class Account:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"<Account {self.name} {SECRET}>"


def describe_account(value):
    if isinstance(value, Account):
        return f"Account(name={value.name!r}, key=<withheld>)"
    return None


def printed(value, *, full_values=False):
    printer = ValuePrinter(describers=[describe_account], full_values=full_values)
    return printer.printed(value).text


def test_a_value_a_package_describes_is_described_on_its_own():
    assert printed(Account("a")) == "Account(name='a', key=<withheld>)"


def test_a_value_a_package_describes_is_described_wherever_it_is():
    for value in (
        [Account("a")],
        (Account("a"),),
        {Account("a")},
        frozenset([Account("a")]),
        {"first": Account("a")},
        [{"accounts": [(1, Account("a"))]}],
    ):
        assert "Account(name='a', key=<withheld>)" in printed(value)
        assert SECRET not in printed(value)
        assert SECRET not in printed(value, full_values=True)


def test_a_container_that_holds_itself_is_printed_once():
    accounts: list = [Account("a")]
    accounts.append(accounts)
    text = printed(accounts)
    assert "Account(name='a', key=<withheld>)" in text
    assert "Recursion on list" in text


def test_the_environment_is_printed_as_its_names():
    with patch(os.environ, "PAYMENTS_KEY", SECRET):
        text = printed(os.environ, full_values=True)
        values = printed(os.environ.values(), full_values=True)
        items = printed(os.environ.items(), full_values=True)

    assert text.startswith(f"environ({len(os.environ) + 1:,} names, values withheld: ")
    assert "PAYMENTS_KEY" in text
    for printed_text in (text, values, items):
        assert "withheld" in printed_text
        assert SECRET not in printed_text


def test_the_environment_inside_something_is_printed_the_same_way():
    with patch(os.environ, "PAYMENTS_KEY", SECRET):
        text = printed([("the environment", os.environ)], full_values=True)

    assert "values withheld" in text
    assert SECRET not in text


def test_a_dict_made_from_the_environment_keeps_what_is_its_own():
    with patch(os.environ, "PAYMENTS_KEY", SECRET):
        for_a_subprocess = {**os.environ, "DEBUG": "1"}
        text = printed(for_a_subprocess, full_values=True)
        inside = printed({"env": {"PAYMENTS_KEY": SECRET}}, full_values=True)

    assert "'DEBUG': '1'" in text
    assert f"<{len(os.environ) + 1:,} names from the environment>" in text
    assert "PAYMENTS_KEY" in text
    assert SECRET not in text
    assert inside == (
        "{'env': {<1 name from the environment>: <values withheld: PAYMENTS_KEY>}}"
    )


def test_a_dict_with_nothing_of_the_environments_is_printed_as_it_is():
    assert printed({"PAYMENTS_KEY": "not what the environment has"}) == (
        "{'PAYMENTS_KEY': 'not what the environment has'}"
    )


def test_a_repr_that_raises_inside_a_container_is_reported_there():
    class Broken:
        def __repr__(self):
            raise ValueError("no")

    text = printed([1, Broken()])
    assert text.startswith("[1,")
    assert text.endswith("Broken: its repr raised ValueError: no>]")


def test_a_large_value_is_printed_once_and_referred_to_after():
    printer = ValuePrinter()
    rows = [{"id": n, "name": f"row number {n}"} for n in range(6)]

    first = printer.printed(rows, name="rows")
    second = printer.printed(list(rows), name="again")
    same_name = printer.printed(rows, name="rows")

    assert first.text.startswith("[{'id': 0")
    assert first.same_as is None
    assert second.text == "<the same as rows>"
    assert second.same_as == "rows"
    # `a == b or a == c` prints `a` under its own name both times.
    assert same_name.text == first.text


def test_a_small_value_is_printed_every_time():
    printer = ValuePrinter()
    assert printer.printed(0, name="total").text == "0"
    assert printer.printed(0, name="count").text == "0"
