import ast

from plain.test import raises
from plain.test.runner.assertions import rewrite_asserts


def run_rewritten(source: str) -> None:
    tree = ast.parse(source)
    tree = rewrite_asserts(tree, source=source)
    code = compile(tree, "<test>", "exec", dont_inherit=True)
    exec(code, {})  # noqa: S102 — the rewritten tree is the thing under test


def test_compare_failure_shows_both_sides():
    with raises(AssertionError) as caught:
        run_rewritten("value = {'a': 1}\nassert value == {'a': 2}\n")
    message = str(caught.exception)
    assert "assert value == {'a': 2}" in message
    assert "left:  {'a': 1}" in message
    assert "right: {'a': 2}" in message


def test_operands_evaluate_once():
    source = (
        "calls = []\n"
        "def side(x):\n"
        "    calls.append(x)\n"
        "    return x\n"
        "assert side(1) == side(1)\n"
        "assert calls == [1, 1]\n"
    )
    run_rewritten(source)


def test_assert_message_is_included():
    with raises(AssertionError) as caught:
        run_rewritten("assert 1 == 2, 'custom message'\n")
    assert "custom message" in str(caught.exception)


def test_truthiness_failure_shows_source():
    with raises(AssertionError) as caught:
        run_rewritten("items = []\nassert items\n")
    assert "assert items" in str(caught.exception)


def test_passing_asserts_are_silent():
    run_rewritten("assert 1 == 1\nassert [1]\nassert 'a' in 'abc'\n")


def test_module_future_imports_still_apply():
    # A test module's own `from __future__ import annotations` must survive
    # the rewrite+compile (and the compiler must not inherit ours).
    run_rewritten(
        "from __future__ import annotations\n"
        "def f(x: SomeUndefinedName) -> AnotherUndefinedName:\n"
        "    return x\n"
        "assert f(1) == 1\n"
    )


def test_failure_shows_the_expression_as_the_test_wrote_it():
    # Without its parentheses this is `"@" in email is valid`, which is a
    # chained comparison and a different expression.
    with raises(AssertionError) as caught:
        run_rewritten(
            'email = "a@example.com"\nvalid = False\nassert ("@" in email) is valid\n'
        )
    message = str(caught.exception)
    assert message.splitlines()[0] == 'assert ("@" in email) is valid'
    assert "left:  True" in message
    assert "right: False" in message


def test_truthiness_failure_keeps_its_parentheses_and_quotes():
    with raises(AssertionError) as caught:
        run_rewritten('a = 1\nb = 1\nassert not (a and b) or (a == "one")\n')
    assert str(caught.exception) == 'assert not (a and b) or (a == "one")'


def test_an_expression_written_over_several_lines_keeps_its_shape():
    with raises(AssertionError) as caught:
        run_rewritten(
            "def check():\n"
            "    result = {'a': 1}\n"
            "    assert result == {\n"
            "        'a': 1,\n"
            "        'b': 2,\n"
            "    }\n"
            "check()\n"
        )
    assert str(caught.exception).splitlines()[:4] == [
        "assert result == {",
        "    'a': 1,",
        "    'b': 2,",
        "}",
    ]


def test_the_expression_is_found_by_bytes_not_characters():
    # The parser counts columns in UTF-8 bytes, and "é" is two of them.
    with raises(AssertionError) as caught:
        run_rewritten('name = "é"; assert name == "e"\n')
    assert str(caught.exception).splitlines()[0] == 'assert name == "e"'


def test_a_form_feed_does_not_count_as_the_end_of_a_line():
    with raises(AssertionError) as caught:
        run_rewritten("first = 1\n\x0csecond = 2\nassert first == second\n")
    assert str(caught.exception).splitlines()[0] == "assert first == second"


def test_a_tab_indented_expression_over_several_lines_keeps_its_shape():
    with raises(AssertionError) as caught:
        run_rewritten(
            "def check():\n"
            "\tresult = {'a': 1}\n"
            "\tassert result == {\n"
            "\t\t'a': 1,\n"
            "\t\t'b': 2,\n"
            "\t}\n"
            "check()\n"
        )
    assert str(caught.exception).splitlines()[:4] == [
        "assert result == {",
        "\t'a': 1,",
        "\t'b': 2,",
        "}",
    ]
