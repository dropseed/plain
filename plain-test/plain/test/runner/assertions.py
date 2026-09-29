"""
Assertion rewriting for test modules.

Bare `assert` is the assertion API. When a test module is loaded, each
assert in it is rewritten so that a failure knows the values inside the
expression: for `assert len(rows) == expected`, what `len(rows)` was, what
`rows` was, and what `expected` was.

An assert becomes:

    a = b = c = NOT_EVALUATED
    try:
        if not ((a := len((b := rows))) == (c := expected)):
            raise failed_assert(..., (a, b, c), message)
    finally:
        del a, b, c

Each part of the expression is wrapped where it stands, in an assignment
expression that keeps its value. Nothing moves, so Python evaluates the
parts in the order it always would, once each, and leaves out the ones it
always would: the right side of an `and` whose left side was false is never
evaluated, and is reported as not evaluated.

What is raised is an ordinary `AssertionError`, with the message the test
gave it or none, as Python would have raised. What was kept travels on it,
for the runner to print. It is kept as it was, not printed here: printing a
value is the runner's to do, once, with what it knows about the run.

The names are deleted whether the assert passes or fails, so an assert
holds on to nothing after it. A test that checks an object has been freed
would otherwise find it alive, in the hands of the assert before.

The expression is shown the way the test file wrote it, taken from the file's
own text. Regenerating it from the syntax tree drops parentheses, and
`("@" in email) is valid` without them is a different expression.
"""

import ast
import re
import textwrap
from dataclasses import dataclass
from typing import Any

__all__ = []

# Names put into rewritten test modules. Unique and greppable.
_FAILED_ASSERT = "__plain_test_failed_assert__"
_NOT_EVALUATED = "__plain_test_not_evaluated__"
_KEPT_VALUE = "__plain_test_{index}__"

# Where a failed assert's values are kept on the AssertionError.
_WATCHED_ASSERT_ATTRIBUTE = "__plain_test_watched_assert__"


class _NotEvaluated:
    """What a part of an expression holds when Python never evaluated it."""

    def __repr__(self) -> str:
        return "<not evaluated>"


NOT_EVALUATED = _NotEvaluated()


@dataclass(frozen=True, kw_only=True)
class WatchedValue:
    """One part of a failed assert's expression, and what it was."""

    # The part as the test file wrote it: `response.status_code`.
    source: str
    # How far inside the expression it is. The two sides of a comparison
    # are 0, what they are made of is 1, and so on.
    depth: int
    # Whether it is one side of a comparison.
    is_operand: bool
    # Whether it is written out in the source (`200`, `{"a": 1}`), so that
    # printing its value would say the same thing twice.
    is_literal: bool
    # The value itself, or NOT_EVALUATED.
    value: Any


@dataclass(frozen=True, kw_only=True)
class WatchedAssert:
    """A failed assert: its expression and the values inside it."""

    # The expression as the test file wrote it, without `assert`.
    expression: str
    # The parts, outermost first, in the order they are written.
    values: tuple[WatchedValue, ...]
    # For `assert left == right`, where the two sides are in `values`.
    equality: tuple[int, int] | None
    # What the test gave after the comma, or None.
    message: Any


def failed_assert(
    expression: str,
    parts: tuple[tuple[str, int, bool, bool], ...],
    equality: tuple[int, int] | None,
    values: tuple[Any, ...],
    message: Any,
) -> AssertionError:
    """
    The error a rewritten assert raises. `parts` is what the rewriter knew
    when the file was compiled, and `values` is what each part was.
    """
    error = AssertionError() if message is None else AssertionError(message)
    watched = WatchedAssert(
        expression=expression,
        values=tuple(
            WatchedValue(
                source=source,
                depth=depth,
                is_operand=is_operand,
                is_literal=is_literal,
                value=value,
            )
            for (source, depth, is_operand, is_literal), value in zip(
                parts, values, strict=True
            )
        ),
        equality=equality,
        message=message,
    )
    setattr(error, _WATCHED_ASSERT_ATTRIBUTE, watched)
    return error


def watched_assert_of(error: BaseException) -> WatchedAssert | None:
    """What a rewritten assert kept, if that is what raised this error."""
    return getattr(error, _WATCHED_ASSERT_ATTRIBUTE, None)


# What ends a line as the parser counts lines. `str.splitlines()` also splits
# on form feeds and a few other characters, which would put every line after
# one at the wrong number.
_LINE_ENDING = re.compile(r"\r\n|\r|\n")


def _lines_with_their_endings(source: str) -> list[str]:
    lines = []
    start = 0
    for ending in _LINE_ENDING.finditer(source):
        lines.append(source[start : ending.end()])
        start = ending.end()
    if start < len(source):
        lines.append(source[start:])
    return lines


def _is_literal(node: ast.expr) -> bool:
    """Whether an expression is a value written out in full."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return isinstance(node.operand, ast.Constant)
    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        return all(_is_literal(element) for element in node.elts)
    if isinstance(node, ast.Dict):
        return all(
            key is not None and _is_literal(key) and _is_literal(value)
            for key, value in zip(node.keys, node.values)
        )
    return False


# Expressions whose value says nothing a reader can use: a function, and a
# generator that the call it was passed to has already used up.
_NEVER_KEPT = (ast.Lambda, ast.GeneratorExp)

# A display's value is what its elements are, which are kept one by one.
# The whole is kept only where it is one side of a comparison.
_DISPLAYS = (ast.List, ast.Tuple, ast.Set, ast.Dict)


class _Watcher:
    """
    Rewrites one assert's expression so that the values inside it are kept,
    and lists what it kept.
    """

    def __init__(self, rewriter: _AssertRewriter) -> None:
        self.rewriter = rewriter
        # (source, depth, is_operand, is_literal), in the order of `values`.
        self.parts: list[tuple[str, int, bool, bool]] = []

    def watch(
        self,
        node: ast.expr,
        *,
        depth: int,
        is_operand: bool = False,
        keep: bool = True,
    ) -> ast.expr:
        """
        The expression, rewritten to keep its value and the values inside
        it. `keep=False` keeps only the ones inside.
        """
        if isinstance(node, _NEVER_KEPT):
            return node

        is_literal = _is_literal(node)
        if is_literal:
            # Nothing inside a literal can be anything but what is written.
            if not is_operand:
                return node
            return self._kept(node, node, depth=depth, is_operand=True, is_literal=True)

        if isinstance(node, ast.NamedExpr):
            # `(total := price())`: what `price()` was is what is wanted,
            # and the name is the test's own to keep.
            node.value = self.watch(node.value, depth=depth, is_operand=is_operand)
            return node

        if isinstance(node, _DISPLAYS) and not is_operand:
            keep = False

        if not keep:
            self._watch_inside(node, depth=depth)
            return node

        # The part is listed before what is inside it, so that the list
        # reads from the outside in.
        index = self._list(node, depth=depth, is_operand=is_operand, is_literal=False)
        self._watch_inside(node, depth=depth + 1)
        return self._assigned(node, index)

    def _kept(
        self,
        original: ast.expr,
        rewritten: ast.expr,
        *,
        depth: int,
        is_operand: bool,
        is_literal: bool,
    ) -> ast.expr:
        index = self._list(
            original, depth=depth, is_operand=is_operand, is_literal=is_literal
        )
        return self._assigned(rewritten, index)

    def _list(
        self, node: ast.expr, *, depth: int, is_operand: bool, is_literal: bool
    ) -> int:
        self.parts.append(
            (self.rewriter.source_on_one_line(node), depth, is_operand, is_literal)
        )
        return len(self.parts) - 1

    def _assigned(self, node: ast.expr, index: int) -> ast.expr:
        """`node`, inside an assignment expression that keeps its value."""
        assigned = ast.NamedExpr(
            target=ast.Name(id=_KEPT_VALUE.format(index=index), ctx=ast.Store()),
            value=node,
        )
        ast.copy_location(assigned, node)
        ast.copy_location(assigned.target, node)
        return assigned

    def _watch_inside(self, node: ast.expr, *, depth: int) -> None:
        """Rewrite, in place, the expressions that `node` is made of."""
        match node:
            case ast.Attribute():
                node.value = self.watch(node.value, depth=depth)
            case ast.Subscript():
                node.value = self.watch(node.value, depth=depth)
                node.slice = self._watch_slice(node.slice, depth=depth)
            case ast.Call():
                self._watch_called(node, depth=depth)
                node.args = [self._watch_element(arg, depth=depth) for arg in node.args]
                for keyword in node.keywords:
                    keyword.value = self.watch(keyword.value, depth=depth)
            case ast.Compare():
                node.left = self.watch(node.left, depth=depth, is_operand=True)
                node.comparators = [
                    self.watch(comparator, depth=depth, is_operand=True)
                    for comparator in node.comparators
                ]
            case ast.BoolOp():
                node.values = [self.watch(value, depth=depth) for value in node.values]
            case ast.UnaryOp():
                node.operand = self.watch(node.operand, depth=depth)
            case ast.BinOp():
                node.left = self.watch(node.left, depth=depth)
                node.right = self.watch(node.right, depth=depth)
            case ast.IfExp():
                # Listed as written, `body if test else orelse`, which is
                # not the order they are evaluated in.
                node.body = self.watch(node.body, depth=depth)
                node.test = self.watch(node.test, depth=depth)
                node.orelse = self.watch(node.orelse, depth=depth)
            case ast.Await():
                # What is awaited is a coroutine, which has nothing to show.
                # What it was called with does.
                node.value = self.watch(node.value, depth=depth, keep=False)
            case ast.List() | ast.Tuple() | ast.Set():
                node.elts = [
                    self._watch_element(element, depth=depth) for element in node.elts
                ]
            case ast.Dict():
                node.keys = [
                    None if key is None else self.watch(key, depth=depth)
                    for key in node.keys
                ]
                node.values = [self.watch(value, depth=depth) for value in node.values]
            case _:
                # A name, which has nothing inside it. Or something kept
                # whole: a comprehension, whose parts are evaluated once for
                # every item and in a scope of their own; an f-string; and
                # any expression this doesn't know.
                pass

    def _watch_called(self, call: ast.Call, *, depth: int) -> None:
        """
        Rewrite what is called. The function isn't kept: `len` is `len`. For
        a method, what it is called on is kept.
        """
        called = call.func
        if isinstance(called, ast.Name):
            return
        if isinstance(called, ast.Attribute):
            called.value = self.watch(called.value, depth=depth)
            return
        call.func = self.watch(called, depth=depth)

    def _watch_element(self, node: ast.expr, *, depth: int) -> ast.expr:
        """An argument, or an element of a display. `*items` keeps `items`."""
        if isinstance(node, ast.Starred):
            node.value = self.watch(node.value, depth=depth)
            return node
        return self.watch(node, depth=depth)

    def _watch_slice(self, node: ast.expr, *, depth: int) -> ast.expr:
        """
        What is between the brackets: `rows[start:stop]` keeps both, and
        `grid[*position]` keeps `position`.
        """
        if isinstance(node, ast.Slice):
            if node.lower is not None:
                node.lower = self.watch(node.lower, depth=depth)
            if node.upper is not None:
                node.upper = self.watch(node.upper, depth=depth)
            if node.step is not None:
                node.step = self.watch(node.step, depth=depth)
            return node
        if isinstance(node, ast.Tuple):
            node.elts = [
                self._watch_slice(element, depth=depth) for element in node.elts
            ]
            return node
        # Neither a slice nor a starred expression is a value on its own, so
        # neither can be kept: only what it is made of can.
        return self._watch_element(node, depth=depth)


def _written_out(value: str | int | bool | tuple | None) -> ast.expr:
    """
    A value the rewriter knows, as the expression that writes it out. The
    compiler puts a tuple of constants in with the code's other constants,
    so an assert that passes builds nothing.
    """
    if isinstance(value, tuple):
        return ast.Tuple(
            elts=[_written_out(element) for element in value], ctx=ast.Load()
        )
    return ast.Constant(value=value)


def _is_not(node: ast.expr) -> bool:
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)


class _AssertRewriter(ast.NodeTransformer):
    def __init__(self, source: str) -> None:
        # Split once for the whole file. `ast.get_source_segment()` splits
        # the source it is given on every call, which for a file with a few
        # hundred asserts is most of the time collection takes.
        self.lines = _lines_with_their_endings(source)

    def source_as_written(self, node: ast.expr) -> str:
        if node.end_lineno is None or node.end_col_offset is None:
            return ast.unparse(node)

        # Column offsets count UTF-8 bytes, not characters.
        first_line = self.lines[node.lineno - 1].encode()
        if node.end_lineno == node.lineno:
            written = first_line[node.col_offset : node.end_col_offset].decode()
            return written.strip()

        # An expression written over several lines keeps its shape: the
        # first line is padded back out to the column it started at, so the
        # continuation lines keep their indentation relative to it. A tab
        # stays a tab, since that is what the lines under it are indented by.
        padding = "".join(
            character if character == "\t" else " "
            for character in first_line[: node.col_offset].decode()
        )
        last_line = self.lines[node.end_lineno - 1].encode()
        written = "".join(
            [
                padding + first_line[node.col_offset :].decode(),
                *self.lines[node.lineno : node.end_lineno - 1],
                last_line[: node.end_col_offset].decode(),
            ]
        )
        return textwrap.dedent(written).strip()

    def source_on_one_line(self, node: ast.expr) -> str:
        """
        A part of an expression, to put in front of its value. As written
        when it was written on one line, and regenerated when it wasn't.
        """
        if node.end_lineno == node.lineno:
            return self.source_as_written(node)
        return ast.unparse(node)

    def visit_Assert(self, node: ast.Assert) -> list[ast.stmt]:
        expression = self.source_as_written(node.test)
        watcher = _Watcher(self)

        # What the whole expression came to is known: it was false. For a
        # comparison, an `and`, an `or` or a `not`, that says everything
        # their value could. For anything else (`assert rows`,
        # `assert response.json_data.get("ok")`) the value is what was
        # false, and is worth seeing.
        says_nothing = isinstance(node.test, ast.Compare | ast.BoolOp) or _is_not(
            node.test
        )
        test = watcher.watch(node.test, depth=0, keep=not says_nothing)

        equality = None
        if (
            isinstance(node.test, ast.Compare)
            and len(node.test.ops) == 1
            and isinstance(node.test.ops[0], ast.Eq)
        ):
            # The two sides are the parts at depth 0. A side that is never
            # kept (a lambda) leaves one, and nothing to compare it with.
            sides = [
                index
                for index, (_, depth, _, _) in enumerate(watcher.parts)
                if depth == 0
            ]
            if len(sides) == 2:
                equality = (sides[0], sides[1])

        kept_names = [
            _KEPT_VALUE.format(index=index) for index in range(len(watcher.parts))
        ]
        # The test's own expressions go in last. They have their places in
        # the file already, and the statements made here are given theirs
        # by walking them, which is a walk these would be most of.
        in_their_place = ast.Constant(value=None)
        failure = ast.Call(
            func=ast.Name(id=_FAILED_ASSERT, ctx=ast.Load()),
            args=[
                _written_out(expression),
                _written_out(tuple(watcher.parts)),
                _written_out(equality),
                ast.Tuple(
                    elts=[ast.Name(id=name, ctx=ast.Load()) for name in kept_names],
                    ctx=ast.Load(),
                ),
                in_their_place,
            ],
            keywords=[],
        )
        is_false = ast.UnaryOp(op=ast.Not(), operand=in_their_place)
        check: ast.stmt = ast.If(
            test=is_false,
            body=[ast.Raise(exc=failure, cause=None)],
            orelse=[],
        )
        statements: list[ast.stmt]
        if not kept_names:
            statements = [check]
        else:
            statements = [
                ast.Assign(
                    targets=[ast.Name(id=name, ctx=ast.Store()) for name in kept_names],
                    value=ast.Name(id=_NOT_EVALUATED, ctx=ast.Load()),
                ),
                ast.Try(
                    body=[check],
                    handlers=[],
                    orelse=[],
                    finalbody=[
                        ast.Delete(
                            targets=[
                                ast.Name(id=name, ctx=ast.Del()) for name in kept_names
                            ]
                        )
                    ],
                ),
            ]

        for statement in statements:
            ast.copy_location(statement, node)
            ast.fix_missing_locations(statement)

        is_false.operand = test
        if node.msg is not None:
            # Evaluated where it is, which is only when the assert fails.
            failure.args[-1] = node.msg
        return statements


def rewrite_asserts(tree: ast.Module, *, source: str) -> ast.Module:
    """
    Rewrite the asserts in a parsed test module, and import what they use.
    `source` is the text `tree` was parsed from.
    """
    tree = _AssertRewriter(source).visit(tree)

    # The import goes after any docstring and __future__ imports.
    insert_at = 0
    for statement in tree.body:
        is_docstring = isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        )
        is_future = (
            isinstance(statement, ast.ImportFrom) and statement.module == "__future__"
        )
        if is_docstring or is_future:
            insert_at += 1
        else:
            break

    what_asserts_use = ast.ImportFrom(
        module="plain.test.runner.assertions",
        names=[
            ast.alias(name="failed_assert", asname=_FAILED_ASSERT),
            ast.alias(name="NOT_EVALUATED", asname=_NOT_EVALUATED),
        ],
        level=0,
    )
    # Locate just the injected node — the rewritten asserts already carry
    # locations, so a whole-tree fix_missing_locations pass isn't needed.
    if tree.body:
        ast.copy_location(what_asserts_use, tree.body[0])
    ast.fix_missing_locations(what_asserts_use)
    tree.body.insert(insert_at, what_asserts_use)
    return tree
