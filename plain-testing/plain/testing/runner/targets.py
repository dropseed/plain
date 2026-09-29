"""
What a target names.

A target is a path, and after it one of three things: nothing, `::` and a
name, or `:` and a line.

    tests/checkout                         every test file under it
    tests/test_signup.py                   every test in the file
    tests/test_signup.py::test_welcome     that test, and every case of it
    tests/test_signup.py:42                the test that line is in

A line is what a failure gives: a traceback says `test_signup.py`, line 42,
and that is enough to run the test again without knowing what it is called.
"""

import ast
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = []


class TargetError(Exception):
    """A target the command was given can't be used: nothing is there, or a
    line is in no test."""


@dataclass(frozen=True, kw_only=True)
class Target:
    # As the command was given it.
    written: str
    path: str
    # What follows `::`, or "".
    name: str = ""
    # What follows `:`, or None.
    line: int | None = None


def read_target(written: str) -> Target:
    path, _, name = written.partition("::")
    if name:
        return Target(written=written, path=path, name=name)

    with_a_line = re.fullmatch(r"(.+):(\d+)", written)
    if with_a_line is not None:
        return Target(written=written, path=with_a_line[1], line=int(with_a_line[2]))
    return Target(written=written, path=written)


@dataclass(frozen=True, kw_only=True)
class _WrittenTest:
    """A test as its file writes it: its name, and the lines it takes up,
    from its first decorator to the last line of its body."""

    name: str
    first_line: int
    last_line: int

    def __str__(self) -> str:
        return f"{self.name} (lines {self.first_line} to {self.last_line})"


def name_of_the_test_at(file: Path, *, line: int, written: str) -> str | None:
    """
    The name of the test a line of a file is in, as a `::` target names it.

    None when the file can't be read as Python: then the file has an error
    of its own to report, which says more than a target's would.

    Raises TargetError when the line is in no test, naming the nearest tests
    above and below it.
    """
    try:
        tree = ast.parse(file.read_text(), filename=str(file))
    except SyntaxError, UnicodeDecodeError:
        return None

    tests = _tests_written_in(tree)
    for test in tests:
        if test.first_line <= line <= test.last_line:
            return test.name

    above = [test for test in tests if test.last_line < line]
    below = [test for test in tests if test.first_line > line]
    if above and below:
        nearest = f"It is between {above[-1]} and {below[0]}."
    elif above:
        nearest = f"It is after the last test, {above[-1]}."
    elif below:
        nearest = f"It is before the first test, {below[0]}."
    else:
        nearest = "The file defines no tests."
    raise TargetError(f"No test at {written}: line {line} is in no test. {nearest}")


def _tests_written_in(tree: ast.Module) -> list[_WrittenTest]:
    tests = []
    for node in tree.body:
        is_a_function = isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        if is_a_function and node.name.startswith("test_"):
            tests.append(_written(node, name=node.name))
    return sorted(tests, key=lambda test: test.first_line)


def _written(
    function: ast.FunctionDef | ast.AsyncFunctionDef, *, name: str
) -> _WrittenTest:
    first_line = min(
        [function.lineno, *(decorator.lineno for decorator in function.decorator_list)]
    )
    assert function.end_lineno is not None
    return _WrittenTest(name=name, first_line=first_line, last_line=function.end_lineno)
