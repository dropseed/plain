import ast

from plain.test import raises
from plain.testing.assertions import rewrite_asserts


def run_rewritten(source: str) -> None:
    tree = ast.parse(source)
    tree = rewrite_asserts(tree)
    code = compile(tree, "<test>", "exec", dont_inherit=True)
    exec(code, {})


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
