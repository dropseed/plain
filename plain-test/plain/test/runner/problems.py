"""
What is wrong with the tests a file defines, and how it is said.

There are two ways to find out. A file that can be run is run, and its
tests are looked at as the functions they are (`collection`). A file that
can't be run is read: what its syntax tree shows about its tests is
reported with the reason it can't be run, so that a file with three things
to fix says all three at once. `tests_as_written` is the reading.

Reading only reports what the syntax tree makes certain. A test under a
decorator this module doesn't know may be passed values by it, so nothing
is said about that test's parameters.
"""

import ast
import textwrap
from dataclasses import dataclass, field

from ..definition import TestDefinitionError

__all__ = []

NO_FIXTURES_ADVICE = (
    "There are no fixtures: nothing is passed to a test by name. A test gets\n"
    "what it needs in its body, by calling a helper or entering a `with`\n"
    "block, and takes values only from @cases(...)."
)

# What to write for a parameter that was one of pytest's fixtures, or one of
# the fixtures Plain's pytest plugin had.
_WHAT_REPLACES_A_FIXTURE = {
    "db": "delete it: every test already runs in a transaction that is rolled back",
    "isolated_db": "`@isolated_db` on the test, from plain.postgres.test",
    "client": "`client = Client()` in the test, from plain.test",
    "settings": "`with override_settings(NAME=value):`, from plain.test",
    "monkeypatch": '`with patch(target, "name", value):`, from plain.test',
    "tmp_path": "`with tempfile.TemporaryDirectory() as directory:`",
    "tmpdir": "`with tempfile.TemporaryDirectory() as directory:`",
    "caplog": "`with capture_logs() as logs:`, from plain.test",
    "capsys": "`with contextlib.redirect_stdout(io.StringIO()) as written:`",
    "capfd": "`with contextlib.redirect_stdout(io.StringIO()) as written:`",
    "request": "pytest's own, with no equivalent: a test's values come from @cases",
    "otel_spans": "`with capture_spans() as spans:`, from plain.test",
    "otel_metrics": "`with capture_metrics() as metrics:`, from plain.test",
    "capture_queries": "`with capture_queries() as queries:`, from plain.postgres.test",
}

_UNITTEST_ISNT_RUN = (
    "unittest isn't run here: nothing would call setUp() or tearDown().\n"
    "Write a class with no base class, named Test*. What setUp() made, each\n"
    "test makes in its body or gets from a helper. `self.assertEqual(a, b)`\n"
    "is `assert a == b`."
)

_A_TEST_IS_RUN_WHERE_IT_IS_DEFINED = (
    "A test is run by the file that defines it, so one that is imported\n"
    "would be left out. Define it in this file. If it isn't a test, import\n"
    "it under a name that doesn't look like one:\n"
    "`from billing import test_connection as check_connection`. A test made\n"
    "by a decorator belongs to the decorator's module until the decorator\n"
    "uses `functools.wraps`."
)

_A_TEST_CANT_YIELD = (
    "A test can't yield: calling a function with a `yield` in it makes a\n"
    "generator, and runs none of its body. Values it yielded to be checked\n"
    "one at a time are passed in with @cases(...). A yield that stood between\n"
    "setup and cleanup belongs in a `@contextmanager` helper, which the test\n"
    "enters with `with`."
)

ONE_CASES_FOR_EVERY_COMBINATION = (
    "Each case is one flat tuple: the test's values, in the order of its\n"
    "parameters. For every combination of two lists, build the cases from\n"
    "both:\n"
    "\n"
    "    @cases(*[(a, b, c) for a in FIRST for b, c in SECOND])\n"
    "\n"
    "Each `for` names what one entry of its list holds: `for a in FIRST`\n"
    "when the entries are single values, `for b, c in SECOND` when they are\n"
    "tuples."
)

# A file with more tests than this to fix says how many, not which.
_MOST_TESTS_NAMED = 3


@dataclass(kw_only=True)
class ProblemsInAFile:
    """What is wrong with the tests one file defines."""

    # A test that can't be run for a reason of its own, and what to write.
    of_one_test: list[str] = field(default_factory=list)
    # The tests with more than one `@cases`, or more than one `parametrize`:
    # the test, which of the two, and how many.
    tests_with_cases_twice: list[tuple[str, str, int]] = field(default_factory=list)
    # Whether running the file would stop at a decorator that raises: a
    # second `@cases`, a `@skip` or `@tag` that isn't called.
    stops_at_a_decorator: bool = False
    # The tests that have a `yield` in them.
    tests_that_yield: list[str] = field(default_factory=list)
    # The classes that are a `unittest.TestCase`.
    unittest_cases: list[str] = field(default_factory=list)
    # The tests that were imported, each with the module it is defined in.
    defined_elsewhere: list[tuple[str, str]] = field(default_factory=list)
    # The tests that take parameters nothing passes in, as they are written:
    # `test_signup(db, client)`.
    tests_taking_parameters: list[str] = field(default_factory=list)
    # Each of those parameters, and how many of the tests take it.
    parameters: dict[str, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(
            self.of_one_test
            or self.tests_with_cases_twice
            or self.tests_that_yield
            or self.unittest_cases
            or self.defined_elsewhere
            or self.tests_taking_parameters
        )

    def what_is_wrong(self, *, fixtures_in_conftests: dict[str, str]) -> str:
        """
        The tests, and what each parameter was. Without the advice about
        fixtures, which a run says once: `NO_FIXTURES_ADVICE`.
        """
        lines = list(self.of_one_test)
        for name, decorator, count in self.tests_with_cases_twice:
            if decorator == "@cases":
                lines.append(f"{name} has {count} @cases. A test takes one.")
            else:
                lines.append(
                    f"{name} has {count} parametrize decorators. "
                    "They become one @cases."
                )
        lines.extend(f"{name} is a unittest.TestCase." for name in self.unittest_cases)
        lines.extend(
            f"{name} is defined in {module}, not in this file."
            for name, module in self.defined_elsewhere
        )
        lines.extend(f"{name}() has a `yield` in it." for name in self.tests_that_yield)

        taking = self.tests_taking_parameters
        if len(taking) > _MOST_TESTS_NAMED:
            lines.append(
                f"{len(taking)} tests take parameters, and nothing passes them in."
            )
        else:
            lines.extend(
                f"{written} takes parameters, and nothing passes them in."
                for written in taking
            )
        sections = [
            "These tests can't be run as written:",
            textwrap.indent("\n".join(lines), "  "),
        ]

        if self.parameters:
            widest = max(len(name) for name in self.parameters)
            table = []
            for name, count in self.parameters.items():
                tests = "1 test" if count == 1 else f"{count} tests"
                what_it_was = fixtures_in_conftests.get(
                    name
                ) or _WHAT_REPLACES_A_FIXTURE.get(name)
                row = f"{name.ljust(widest)}  {tests}"
                if what_it_was is not None:
                    row = f"{row}  {what_it_was}"
                table.append(row)
            sections.append(textwrap.indent("\n".join(table), "  "))
        if self.tests_with_cases_twice:
            sections.append(ONE_CASES_FOR_EVERY_COMBINATION)
        if self.unittest_cases:
            sections.append(_UNITTEST_ISNT_RUN)
        if self.defined_elsewhere:
            sections.append(_A_TEST_IS_RUN_WHERE_IT_IS_DEFINED)
        if self.tests_that_yield:
            sections.append(_A_TEST_CANT_YIELD)
        return "\n\n".join(sections)


class CantBeRunAsWritten(TestDefinitionError):
    """
    A file's tests can't be run as they are written. `collection` says it,
    with what the run knows: which fixtures its conftest files had, and
    what it has said already for another file.
    """

    def __init__(self, tests: ProblemsInAFile) -> None:
        self.tests = tests
        super().__init__(tests.what_is_wrong(fixtures_in_conftests={}))


# ---------------------------------------------------------------------------
# Reading a file's tests from its syntax tree
# ---------------------------------------------------------------------------

# Decorators that pass a test nothing, by where they come from.
_PASSES_NOTHING = (
    "plain.test.skip",
    "plain.test.tag",
    "plain.postgres.test.isolated_db",
    "pytest.mark.",
)

_CASES = "plain.test.cases"
_PARAMETRIZE = "pytest.mark.parametrize"
_NEEDS_TO_BE_CALLED = {
    "plain.test.skip": '@skip requires a reason: @skip("why")',
    "plain.test.tag": '@tag requires at least one name: @tag("slow")',
}

type _Function = ast.FunctionDef | ast.AsyncFunctionDef


def _names_imported(tree: ast.Module) -> dict[str, str]:
    """
    What each name a module imports stands for: `{"cases": "plain.test.cases",
    "pt": "pytest"}`.
    """
    names = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname is not None:
                    names[alias.asname] = alias.name
                else:
                    # `import plain.test` binds `plain`.
                    top = alias.name.split(".")[0]
                    names[top] = top
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return names


def _dotted(node: ast.expr) -> str | None:
    """`pytest.mark.skip` for the expression that says so, or None."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _where_it_comes_from(node: ast.expr, *, imported: dict[str, str]) -> str | None:
    """What an expression names, by the module it was imported from."""
    dotted = _dotted(node)
    if dotted is None:
        return None
    first, _, rest = dotted.partition(".")
    origin = imported.get(first)
    if origin is None:
        return None
    return f"{origin}.{rest}" if rest else origin


def _yields(function: _Function) -> bool:
    """Whether a function's own body has a `yield`: not a function inside it."""
    inside: list[ast.AST] = list(function.body)
    while inside:
        node = inside.pop()
        if isinstance(node, ast.Yield | ast.YieldFrom):
            return True
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            continue
        if isinstance(node, ast.ClassDef):
            continue
        inside.extend(ast.iter_child_nodes(node))
    return False


def _names_parametrize_fills(decorator: ast.Call) -> list[str] | None:
    """
    The parameters a `parametrize` passes values for, from its first
    argument, or None when that isn't written out where it can be read.
    """
    if not decorator.args:
        return None
    names = decorator.args[0]
    if isinstance(names, ast.Constant) and isinstance(names.value, str):
        return [name.strip() for name in names.value.split(",") if name.strip()]
    if isinstance(names, ast.List | ast.Tuple):
        found = []
        for element in names.elts:
            if not (
                isinstance(element, ast.Constant) and isinstance(element.value, str)
            ):
                return None
            found.append(element.value)
        return found
    return None


def _read_a_test(
    function: _Function,
    *,
    name: str,
    in_a_class: bool,
    imported: dict[str, str],
    problems: ProblemsInAFile,
) -> None:
    if _yields(function):
        problems.tests_that_yield.append(name)
        return

    filled_by_the_call = 1 if in_a_class else 0
    filled_by_parametrize: list[str] = []
    times_cases = 0
    times_parametrize = 0
    # Whether every decorator is one this module knows passes no values
    # but the ones counted here.
    parameters_are_known = True

    for decorator in function.decorator_list:
        called = decorator.func if isinstance(decorator, ast.Call) else decorator
        origin = _where_it_comes_from(called, imported=imported)

        if isinstance(decorator, ast.Name | ast.Attribute):
            if origin in _NEEDS_TO_BE_CALLED:
                problems.of_one_test.append(
                    f"line {decorator.lineno}: {_NEEDS_TO_BE_CALLED[origin]}"
                )
                problems.stops_at_a_decorator = True
                continue
            if isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
                filled_by_the_call = 0
                continue
            if isinstance(decorator, ast.Name) and decorator.id == "classmethod":
                continue

        if origin == _CASES:
            times_cases += 1
            parameters_are_known = False  # its values fill them, by position
        elif origin == _PARAMETRIZE and isinstance(decorator, ast.Call):
            times_parametrize += 1
            names = _names_parametrize_fills(decorator)
            if names is None:
                parameters_are_known = False
            else:
                filled_by_parametrize.extend(names)
        elif origin is None or not origin.startswith(_PASSES_NOTHING):
            parameters_are_known = False

    where = f"line {function.lineno}: {name}"
    if times_cases > 1:
        problems.tests_with_cases_twice.append((where, "@cases", times_cases))
        problems.stops_at_a_decorator = True
    if times_parametrize > 1:
        problems.tests_with_cases_twice.append(
            (where, "parametrize", times_parametrize)
        )

    if not parameters_are_known:
        return

    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    with_no_default = positional[: len(positional) - len(arguments.defaults)]
    keyword_only = [
        argument
        for argument, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        )
        if default is None
    ]
    nothing_fills = [
        argument
        for argument in [*with_no_default[filled_by_the_call:], *keyword_only]
        if argument.arg not in filled_by_parametrize
    ]
    if not nothing_fills:
        return

    every_parameter = [*positional[filled_by_the_call:], *arguments.kwonlyargs]
    written = ", ".join(ast.unparse(argument) for argument in every_parameter)
    problems.tests_taking_parameters.append(f"{name}({written})")
    for argument in nothing_fills:
        problems.parameters[argument.arg] = problems.parameters.get(argument.arg, 0) + 1


def tests_as_written(tree: ast.Module) -> ProblemsInAFile:
    """
    What is wrong with a file's tests, as far as reading it can tell. A
    test imported from another module is left to `collection`: whether an
    imported name is a test depends on what it is, not what it is called.
    """
    imported = _names_imported(tree)
    problems = ProblemsInAFile()

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name.startswith("test_"):
                _read_a_test(
                    node,
                    name=node.name,
                    in_a_class=False,
                    imported=imported,
                    problems=problems,
                )

        elif isinstance(node, ast.ClassDef):
            is_a_unittest_case = any(
                _where_it_comes_from(base, imported=imported)
                in ("unittest.TestCase", "unittest.case.TestCase")
                for base in node.bases
            )
            if is_a_unittest_case:
                problems.unittest_cases.append(node.name)
                continue
            if not node.name.startswith("Test"):
                continue
            for member in node.body:
                if isinstance(
                    member, ast.FunctionDef | ast.AsyncFunctionDef
                ) and member.name.startswith("test_"):
                    _read_a_test(
                        member,
                        name=f"{node.name}::{member.name}",
                        in_a_class=True,
                        imported=imported,
                        problems=problems,
                    )

    return problems
