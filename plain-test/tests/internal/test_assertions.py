"""The rewriter: what a rewritten assert does, and what it keeps.

What a failure prints is tested in `public/test_failure_output.py`.
"""

import ast
import asyncio
from typing import Any

from plain.test import case, cases, raises
from plain.test.runner.assertions import (
    NOT_EVALUATED,
    WatchedAssert,
    rewrite_asserts,
    watched_assert_of,
)


def run_rewritten(
    source: str, *, names: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Run a module's source with its asserts rewritten. Returns its names,
    and fills `names` with them when the source raises before it can.
    """
    tree = ast.parse(source)
    tree = rewrite_asserts(tree, source=source)
    code = compile(tree, "<test>", "exec", dont_inherit=True)
    if names is None:
        names = {}
    exec(code, names)  # noqa: S102 — the rewritten tree is the thing under test
    return names


def failed(source: str) -> WatchedAssert:
    """What the assert that fails in `source` kept."""
    with raises(AssertionError) as caught:
        run_rewritten(source)
    watched = watched_assert_of(caught.exception)
    assert watched is not None
    return watched


def kept(watched: WatchedAssert) -> list[tuple[int, str, Any]]:
    """The parts that aren't written out, as (depth, source, value)."""
    return [
        (value.depth, value.source, value.value)
        for value in watched.values
        if not value.is_literal
    ]


# What is raised


def test_what_is_raised_is_what_python_would_have_raised():
    with raises(AssertionError) as caught:
        run_rewritten("assert 1 == 2\n")
    assert type(caught.exception) is AssertionError
    assert caught.exception.args == ()
    assert str(caught.exception) == ""


def test_the_message_is_the_errors_message():
    with raises(AssertionError) as caught:
        run_rewritten("assert 1 == 2, 'the total should include shipping'\n")
    assert caught.exception.args == ("the total should include shipping",)
    watched = watched_assert_of(caught.exception)
    assert watched is not None
    assert watched.message == "the total should include shipping"


def test_the_message_is_evaluated_only_when_the_assert_fails():
    names = run_rewritten(
        "made = []\n"
        "def message():\n"
        "    made.append('message')\n"
        "    return 'why'\n"
        "assert 1 == 1, message()\n"
    )
    assert names["made"] == []

    with raises(AssertionError, match="why"):
        run_rewritten("def message():\n    return 'why'\nassert 1 == 2, message()\n")


def test_an_error_raised_inside_the_expression_is_that_error():
    with raises(KeyError) as caught:
        run_rewritten("settings = {}\nassert settings['missing'] == 1\n")
    assert watched_assert_of(caught.exception) is None


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


# What is kept


def test_the_values_inside_the_expression_are_kept_from_the_outside_in():
    watched = failed("rows = [1, 2]\nexpected = 3\nassert len(rows) == expected\n")
    assert kept(watched) == [
        (0, "len(rows)", 2),
        (1, "rows", [1, 2]),
        (0, "expected", 3),
    ]


def test_an_attribute_keeps_what_it_is_an_attribute_of():
    watched = failed(
        "class Response:\n"
        "    status_code = 404\n"
        "response = Response()\n"
        "assert response.status_code == 200\n"
    )
    (status, response) = kept(watched)
    assert status == (0, "response.status_code", 404)
    assert response[:2] == (1, "response")


def test_a_method_call_keeps_what_it_was_called_on_and_with():
    watched = failed("data = {'ok': False}\nkey = 'ok'\nassert data.get(key)\n")
    assert kept(watched) == [
        (0, "data.get(key)", False),
        (1, "data", {"ok": False}),
        (1, "key", "ok"),
    ]


def test_the_function_that_is_called_is_not_kept():
    watched = failed("assert len([]) == 1\n")
    assert [source for _, source, _ in kept(watched)] == ["len([])"]


def test_what_is_written_out_is_kept_only_as_a_side_of_a_comparison():
    watched = failed("total = 41\nassert total == 42\n")
    assert [(value.source, value.is_literal) for value in watched.values] == [
        ("total", False),
        ("42", True),
    ]
    assert watched.equality == (0, 1)


def test_only_a_single_equality_has_two_sides_to_diff():
    assert failed("a = 1\nassert a != 1\n").equality is None
    assert failed("a = 1\nassert a == 2 == 3\n").equality is None
    assert failed("a = []\nassert a\n").equality is None


def test_a_subscript_keeps_what_is_between_the_brackets():
    watched = failed(
        "rows = [1, 2, 3]\nstart = 1\nstop = 2\nassert rows[start:stop] == []\n"
    )
    assert kept(watched) == [
        (0, "rows[start:stop]", [2]),
        (1, "rows", [1, 2, 3]),
        (1, "start", 1),
        (1, "stop", 2),
    ]


def test_a_not_keeps_what_was_true():
    watched = failed("errors = ['required']\nassert not errors\n")
    assert kept(watched) == [(0, "errors", ["required"])]


def test_a_comparison_inside_an_expression_keeps_what_it_came_to():
    watched = failed("a = 1\nb = 1\nvalid = False\nassert (a == b) is valid\n")
    assert kept(watched) == [
        (0, "a == b", True),
        (1, "a", 1),
        (1, "b", 1),
        (0, "valid", False),
    ]


def test_arithmetic_keeps_what_it_came_to():
    watched = failed("price = 10\ncount = 3\nassert price * count == 40\n")
    assert kept(watched) == [
        (0, "price * count", 30),
        (1, "price", 10),
        (1, "count", 3),
    ]


def test_a_display_keeps_its_elements():
    watched = failed("a = 1\nb = 2\nassert [a, b] == [1, 3]\n")
    assert kept(watched) == [(0, "[a, b]", [1, 2]), (1, "a", 1), (1, "b", 2)]


def test_an_f_string_is_kept_whole():
    watched = failed("name = 'a'\nassert f'{name}-{name!r}' == 'a-b'\n")
    assert kept(watched) == [(0, "f'{name}-{name!r}'", "a-'a'")]


def test_a_comprehension_is_kept_whole():
    watched = failed("rows = [1, 2]\nassert [n * 2 for n in rows] == [2, 5]\n")
    assert kept(watched) == [(0, "[n * 2 for n in rows]", [2, 4])]


def test_a_generator_passed_to_a_call_is_not_kept():
    watched = failed("rows = [1, 2]\nassert all(n > 1 for n in rows)\n")
    assert kept(watched) == [(0, "all(n > 1 for n in rows)", False)]


def test_a_part_written_over_several_lines_is_named_on_one():
    watched = failed(
        "def total(*prices):\n"
        "    return sum(prices)\n"
        "assert total(\n"
        "    1,\n"
        "    2,\n"
        ") == 4\n"
    )
    assert kept(watched) == [(0, "total(1, 2)", 3)]


# Evaluated once, in order, and only what Python would evaluate


def test_every_part_is_evaluated_once_and_in_order():
    names = run_rewritten(
        "calls = []\n"
        "def side(x):\n"
        "    calls.append(x)\n"
        "    return x\n"
        "assert side(1) + side(2) == side(3)\n"
        "assert side(side(4)) in [side(4)]\n"
    )
    assert names["calls"] == [1, 2, 3, 4, 4, 4]


def test_a_part_with_a_side_effect_has_it_once_when_the_assert_fails():
    names: dict[str, Any] = {}
    with raises(AssertionError):
        run_rewritten(
            "sent = []\n"
            "def send(message):\n"
            "    sent.append(message)\n"
            "    return len(sent)\n"
            "assert send('hello') == 2\n",
            names=names,
        )
    assert names["sent"] == ["hello"]


def test_a_generator_is_run_through_once():
    names = run_rewritten(
        "yielded = []\n"
        "def numbers():\n"
        "    for n in [1, 2, 3]:\n"
        "        yielded.append(n)\n"
        "        yield n\n"
        "generator = numbers()\n"
        "assert list(generator) == [1, 2, 3]\n"
        "assert list(generator) == []\n"
        "assert sum(n for n in numbers()) == 6\n"
    )
    assert names["yielded"] == [1, 2, 3, 1, 2, 3]


def test_the_right_side_of_an_and_is_left_alone_when_the_left_is_false():
    watched = failed(
        "def explode():\n"
        "    raise RuntimeError('never called')\n"
        "items = []\n"
        "assert items and explode()\n"
    )
    assert kept(watched) == [(0, "items", []), (0, "explode()", NOT_EVALUATED)]


def test_the_right_side_of_an_or_is_left_alone_when_the_left_is_true():
    names = run_rewritten(
        "calls = []\n"
        "def called():\n"
        "    calls.append(1)\n"
        "    return True\n"
        "assert True or called()\n"
        "value = 1\n"
        "assert value or called()\n"
    )
    assert names["calls"] == []


def test_a_chained_comparison_stops_where_python_stops():
    watched = failed(
        "calls = []\n"
        "def value(n):\n"
        "    calls.append(n)\n"
        "    return n\n"
        "assert value(5) < value(2) < value(9)\n"
    )
    assert kept(watched) == [
        (0, "value(5)", 5),
        (0, "value(2)", 2),
        (0, "value(9)", NOT_EVALUATED),
    ]


def test_a_conditional_expression_evaluates_one_branch():
    watched = failed(
        "def explode():\n"
        "    raise RuntimeError('never called')\n"
        "ready = False\n"
        "fallback = 0\n"
        "assert (explode() if ready else fallback)\n"
    )
    assert kept(watched) == [
        (0, "explode() if ready else fallback", 0),
        (1, "explode()", NOT_EVALUATED),
        (1, "ready", False),
        (1, "fallback", 0),
    ]


def test_a_part_that_was_not_evaluated_last_time_is_not_shown_from_before():
    # The same assert runs twice. The second time, the right side is never
    # evaluated, and must not be reported as what it was the first time.
    watched = failed(
        "for left, right in [(1, 1), (0, 5)]:\n    assert left and right == 1\n"
    )
    assert kept(watched) == [
        (0, "left", 0),
        (0, "right == 1", NOT_EVALUATED),
        (1, "right", NOT_EVALUATED),
    ]


# Expressions that have to come through with their meaning intact


@cases(
    "values = [3, 4]\nassert (total := sum(values)) == 7\nassert total == 7\n",
    "double = lambda n: n * 2\nassert (lambda n: n + 1)(double(2)) == 5\n",
    "rows = [1, 2]\nassert {n: n * 2 for n in rows} == {1: 2, 2: 4}\n",
    "rows = [1, 2]\nassert {n for n in rows} == {1, 2}\n",
    "def add(*numbers, **named):\n"
    "    return sum(numbers) + sum(named.values())\n"
    "some = [1, 2]\n"
    "more = {'a': 3}\n"
    "assert add(*some, 4, **more, b=5) == 15\n",
    "first = [1]\nrest = [2, 3]\nassert [*first, *rest] == [1, 2, 3]\n",
    "defaults = {'a': 1}\nassert {**defaults, 'b': 2} == {'a': 1, 'b': 2}\n",
    "name = 'x'\nwidth = 3\nassert f'{name:>{width}}' == '  x'\n",
    "name = 'x'\nassert f'{name=}' == \"name='x'\"\n",
    "grid = [[1, 2], [3, 4]]\nassert grid[1][0] == 3\nassert grid[-1][::-1] == [4, 3]\n",
    "value = -1\nassert -value == 1\nassert not value == 1\nassert ~value == 0\n",
    "assert ...\n",
    "class Settings:\n    debug = True\n    assert debug\n",
)
def test_an_expression_comes_through_with_its_meaning(source):
    run_rewritten(source)


# Every kind of expression there is, where an assert can have it. Each one
# says what it evaluates through `seen()`, which writes it down.

WRITES_DOWN_WHAT_IS_EVALUATED = (
    "log = []\n"
    "def seen(value, label=None):\n"
    "    log.append(value if label is None else label)\n"
    "    return value\n"
    "class Grid:\n"
    "    def __getitem__(self, key):\n"
    "        return key\n"
    "grid = Grid()\n"
)

# Named for the class of `ast.expr` each is there for.
EXPRESSIONS_BY_KIND = {
    "Attribute": ["class A:\n    b = 1\nassert seen(A, 'A').b == 1\n"],
    "Await": [
        (
            "async def get(v):\n    return seen(v)\n"
            "async def main():\n"
            "    assert await get(seen(1, 'argument')) == 1\n"
            "    assert [await get(x) for x in [2]] == [2]\n"
        )
    ],
    "BinOp": [
        "assert seen(1) + seen(2) * seen(3) == 7\n",
        "assert seen(7) // seen(2) == 3 and seen(2) ** seen(3) == 8\n",
    ],
    "BoolOp": ["assert seen(1) and seen(2) or seen(3)\n"],
    "Call": [
        "assert max(seen(1), seen(2), key=seen(None, 'key')) == 2\n",
        (
            "def f(*a, **k):\n    return (a, k)\n"
            "xs = [1]\nks = {'a': 2}\n"
            "assert f(*seen(xs, 'xs'), **seen(ks, 'ks')) == ((1,), {'a': 2})\n"
        ),
    ],
    "Compare": [
        "assert seen(1) < seen(2) < seen(3) != seen(4)\n",
        "xs = [1]\nassert seen(1) in seen(xs, 'xs') and seen(2) not in xs\n",
        "assert seen(None, 'none') is None\n",
    ],
    "Constant": ["assert 1 == seen(1) and 'a' and ... and b'x' and 1.5\n"],
    "Dict": [
        (
            "d = {'a': 1}\n"
            "assert {**seen(d, 'd'), seen('b'): seen(2)} == {'a': 1, 'b': 2}\n"
        )
    ],
    "DictComp": ["assert {seen(x): x for x in seen([1, 2], 'rows')} == {1: 1, 2: 2}\n"],
    "FormattedValue": ["w = 3\nassert f'{seen(1):>{seen(w)}}{seen(2)!r}' == '  12'\n"],
    "GeneratorExp": ["assert sum(seen(x) for x in seen([1, 2], 'rows')) == 3\n"],
    "IfExp": ["assert (seen(1) if seen(True, 'test') else seen(2)) == 1\n"],
    "Interpolation": ["assert t'{seen(1)}'.interpolations[0].value == 1\n"],
    "JoinedStr": ["assert f'{seen(1)}-{seen(2)}' == '1-2'\n"],
    "Lambda": ["assert (lambda x: seen(x))(seen(1)) == 1\n"],
    "List": ["xs = [1]\nassert [*seen(xs, 'xs'), seen(2)] == [1, 2]\n"],
    "ListComp": [
        "assert [seen(x) for x in seen([1, 2], 'rows')] == [1, 2]\n",
        "assert [y for x in [1, 2] if (y := seen(x))] == [1, 2]\n",
    ],
    "Name": ["x = seen(1)\nassert x\n"],
    "NamedExpr": ["assert (n := seen(3)) + seen(n) == 6\n"],
    "Set": ["xs = [1]\nassert {*seen(xs, 'xs'), seen(2)} == {1, 2}\n"],
    "SetComp": ["assert {seen(x) for x in seen([1, 2], 'rows')} == {1, 2}\n"],
    "Slice": [
        "xs = [1, 2, 3]\nassert xs[seen(0) : seen(2) : seen(1)] == [1, 2]\n",
        (
            "assert grid[seen(1) : seen(2), :: seen(3)] == "
            "(slice(1, 2), slice(None, None, 3))\n"
        ),
    ],
    "Starred": [
        "at = (1, 2)\nassert grid[*seen(at, 'at')] == (1, 2)\n",
        (
            "at = (1,)\n"
            "assert grid[*seen(at, 'at'), seen(2) : seen(3)] == (1, slice(2, 3))\n"
        ),
        "xs = [1]\nassert (*seen(xs, 'xs'), 3) == (1, 3)\n",
    ],
    "Subscript": [
        "xs = [1, 2]\nassert seen(xs, 'xs')[seen(0)] == 1\n",
        "assert grid[seen(1), ...] == (1, ...)\n",
    ],
    "TemplateStr": ["assert t'{seen(1)}-{seen(2)}'.strings == ('', '-', '')\n"],
    "Tuple": ["assert [seen(1), (seen(2), seen(3))] == [1, (2, 3)]\n"],
    "UnaryOp": ["assert -seen(1) == -1 and not seen(0) and ~seen(0) == -1\n"],
    "Yield": [
        ("def asks():\n    assert (yield seen(1)) == 'answer'\n    yield 'done'\n")
    ],
    "YieldFrom": [
        (
            "def gives():\n"
            "    assert (yield from seen([1], 'rows')) is None\n"
            "    yield 'done'\n"
        )
    ],
}


def what_running_it_evaluates(source: str, *, rewritten: bool) -> list[Any]:
    """Run a module that uses `seen()`, and say what it saw, in order."""
    source = WRITES_DOWN_WHAT_IS_EVALUATED + source
    tree = ast.parse(source)
    if rewritten:
        tree = rewrite_asserts(tree, source=source)
    names: dict[str, Any] = {}
    exec(compile(tree, "<test>", "exec", dont_inherit=True), names)  # noqa: S102
    if "main" in names:
        asyncio.run(names["main"]())
    if "asks" in names:
        asking = names["asks"]()
        assert next(asking) == 1
        assert asking.send("answer") == "done"
    if "gives" in names:
        assert list(names["gives"]()) == [1, "done"]
    return names["log"]


def test_there_is_an_expression_for_every_kind_there_is():
    # A Python that adds a kind of expression fails here, until the list
    # above has one that uses it.
    every_kind = {kind.__name__ for kind in ast.expr.__subclasses__()}
    assert sorted(EXPRESSIONS_BY_KIND) == sorted(every_kind)


@cases(
    *(
        case(source, id=f"{kind} {number}")
        for kind, sources in EXPRESSIONS_BY_KIND.items()
        for number, source in enumerate(sources)
    )
)
def test_every_kind_of_expression_evaluates_what_it_did_before(source):
    as_written = what_running_it_evaluates(source, rewritten=False)
    assert as_written != []
    assert what_running_it_evaluates(source, rewritten=True) == as_written


def test_a_starred_subscript_keeps_what_is_starred():
    watched = failed(
        "class Grid:\n"
        "    def __getitem__(self, key):\n"
        "        return key\n"
        "grid = Grid()\n"
        "at = (1, 2)\n"
        "assert grid[*at] == (3, 4)\n"
    )
    assert kept(watched) == [
        (0, "grid[*at]", (1, 2)),
        (1, "grid", watched.values[1].value),
        (1, "at", (1, 2)),
    ]


def test_a_template_string_is_kept_whole():
    watched = failed("name = 'a'\nassert t'{name}'.strings == ('x',)\n")
    assert [source for _, source, _ in kept(watched)] == [
        "t'{name}'.strings",
        "t'{name}'",
    ]


def test_an_awaited_call_keeps_what_was_awaited_and_not_the_coroutine():
    names = run_rewritten(
        "async def fetch(path):\n"
        "    return 404\n"
        "async def check():\n"
        "    path = '/missing'\n"
        "    assert await fetch(path) == 200\n"
    )
    with raises(AssertionError) as caught:
        asyncio.run(names["check"]())
    watched = watched_assert_of(caught.exception)
    assert watched is not None
    assert kept(watched) == [(0, "await fetch(path)", 404), (1, "path", "/missing")]


def test_a_yield_in_an_assert_still_yields():
    names = run_rewritten(
        "def ask():\n    assert (yield 'question') == 'answer'\n    yield 'done'\n"
    )
    asking = names["ask"]()
    assert next(asking) == "question"
    assert asking.send("answer") == "done"


# What an assert leaves behind


def test_an_assert_that_passes_leaves_no_names_behind():
    names = run_rewritten(
        "def check():\n"
        "    rows = [1]\n"
        "    assert len(rows) == 1\n"
        "    return sorted(locals())\n"
        "left_in_the_function = check()\n"
        "assert len([1]) == 1\n"
    )
    assert names["left_in_the_function"] == ["rows"]
    assert not [name for name in names if name.startswith("__plain_test_0")]


def test_an_assert_that_fails_leaves_no_names_behind():
    names = run_rewritten(
        "def check():\n"
        "    rows = [1]\n"
        "    try:\n"
        "        assert len(rows) == 2\n"
        "    except AssertionError:\n"
        "        pass\n"
        "    return sorted(locals())\n"
        "left_in_the_function = check()\n"
    )
    assert names["left_in_the_function"] == ["rows"]


def test_an_assert_does_not_keep_an_object_alive():
    # The second assert is about an object the first one had in hand.
    run_rewritten(
        "import weakref\n"
        "class Thing:\n"
        "    pass\n"
        "def check():\n"
        "    thing = Thing()\n"
        "    watching = weakref.ref(thing)\n"
        "    assert watching() is not None\n"
        "    del thing\n"
        "    assert watching() is None\n"
        "check()\n"
    )


# The expression, as the test file wrote it


def test_the_expression_is_the_one_the_test_wrote():
    # Without its parentheses this is `"@" in email is valid`, which is a
    # chained comparison and a different expression.
    watched = failed(
        'email = "a@example.com"\nvalid = False\nassert ("@" in email) is valid\n'
    )
    assert watched.expression == '("@" in email) is valid'


def test_the_expression_keeps_its_parentheses_and_quotes():
    watched = failed('a = 1\nb = 1\nassert not (a and b) or (a == "one")\n')
    assert watched.expression == 'not (a and b) or (a == "one")'


def test_an_expression_written_over_several_lines_keeps_its_shape():
    watched = failed(
        "def check():\n"
        "    result = {'a': 1}\n"
        "    assert result == {\n"
        "        'a': 1,\n"
        "        'b': 2,\n"
        "    }\n"
        "check()\n"
    )
    assert watched.expression.splitlines() == [
        "result == {",
        "    'a': 1,",
        "    'b': 2,",
        "}",
    ]


def test_the_expression_is_found_by_bytes_not_characters():
    # The parser counts columns in UTF-8 bytes, and "é" is two of them.
    watched = failed('name = "é"; assert name == "e"\n')
    assert watched.expression == 'name == "e"'
    assert kept(watched) == [(0, "name", "é")]


def test_a_form_feed_does_not_count_as_the_end_of_a_line():
    watched = failed("first = 1\n\x0csecond = 2\nassert first == second\n")
    assert watched.expression == "first == second"


def test_a_tab_indented_expression_over_several_lines_keeps_its_shape():
    watched = failed(
        "def check():\n"
        "\tresult = {'a': 1}\n"
        "\tassert result == {\n"
        "\t\t'a': 1,\n"
        "\t\t'b': 2,\n"
        "\t}\n"
        "check()\n"
    )
    assert watched.expression.splitlines() == [
        "result == {",
        "\t'a': 1,",
        "\t'b': 2,",
        "}",
    ]
