"""
Assertion rewriting for test modules.

Bare `assert` is the assertion API. When the collector imports a test module,
it rewrites simple comparison asserts so failures show both sides of the
comparison instead of a bare AssertionError.

The rewrite is deliberately narrow: single-operator comparisons get rich
output; everything else falls back to showing the asserted expression source.
Each operand is evaluated exactly once, preserving the original semantics.

The expression is shown the way the test file wrote it, taken from the file's
own text. Regenerating it from the syntax tree drops parentheses, and
`("@" in email) is valid` without them is a different expression.
"""

import ast
import reprlib
import textwrap
from typing import Any

__all__ = []

# Names injected into rewritten test modules. Unique and greppable.
_FORMAT_COMPARE = "__plain_testing_format_compare__"
_FORMAT_TRUTH = "__plain_testing_format_truth__"
_LEFT = "__plain_testing_left__"
_RIGHT = "__plain_testing_right__"

# The comparisons that get `left:` and `right:` values on failure.
_COMPARISONS: tuple[type[ast.cmpop], ...] = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
)

_repr = reprlib.Repr()
_repr.maxstring = 400
_repr.maxother = 400
_repr.maxlist = 20
_repr.maxdict = 20


def format_compare(source: str, left: Any, right: Any, msg: Any = None) -> str:
    lines = []
    if msg is not None:
        lines.append(str(msg))
    lines.append(f"assert {source}")
    lines.append(f"  left:  {_repr.repr(left)}")
    lines.append(f"  right: {_repr.repr(right)}")
    return "\n".join(lines)


def format_truth(source: str, msg: Any = None) -> str:
    if msg is not None:
        return f"{msg}\nassert {source}"
    return f"assert {source}"


class _AssertRewriter(ast.NodeTransformer):
    def __init__(self, source: str) -> None:
        self.source = source

    def _source_as_written(self, node: ast.expr) -> str:
        # padded: a continuation line keeps its indentation relative to the
        # first, so an expression written over several lines keeps its shape.
        written = ast.get_source_segment(self.source, node, padded=True)
        if written is None:
            return ast.unparse(node)
        return textwrap.dedent(written).strip()

    def visit_Assert(self, node: ast.Assert) -> list[ast.stmt] | ast.stmt:
        test = node.test
        msg_expr = node.msg if node.msg is not None else ast.Constant(value=None)

        if (
            isinstance(test, ast.Compare)
            and len(test.ops) == 1
            and isinstance(test.ops[0], _COMPARISONS)
        ):
            return self._rewrite_compare(node, test, msg_expr)

        return self._rewrite_truth(node, test, msg_expr)

    def _rewrite_compare(
        self, node: ast.Assert, test: ast.Compare, msg_expr: ast.expr
    ) -> list[ast.stmt]:
        source = self._source_as_written(test)

        assign_left = ast.Assign(
            targets=[ast.Name(id=_LEFT, ctx=ast.Store())],
            value=test.left,
        )
        assign_right = ast.Assign(
            targets=[ast.Name(id=_RIGHT, ctx=ast.Store())],
            value=test.comparators[0],
        )
        recompare = ast.Compare(
            left=ast.Name(id=_LEFT, ctx=ast.Load()),
            ops=test.ops,
            comparators=[ast.Name(id=_RIGHT, ctx=ast.Load())],
        )
        raise_stmt = ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="AssertionError", ctx=ast.Load()),
                args=[
                    ast.Call(
                        func=ast.Name(id=_FORMAT_COMPARE, ctx=ast.Load()),
                        args=[
                            ast.Constant(value=source),
                            ast.Name(id=_LEFT, ctx=ast.Load()),
                            ast.Name(id=_RIGHT, ctx=ast.Load()),
                            msg_expr,
                        ],
                        keywords=[],
                    )
                ],
                keywords=[],
            ),
            cause=None,
        )
        check = ast.If(
            test=ast.UnaryOp(op=ast.Not(), operand=recompare),
            body=[raise_stmt],
            orelse=[],
        )

        statements: list[ast.stmt] = [assign_left, assign_right, check]
        for statement in statements:
            ast.copy_location(statement, node)
            ast.fix_missing_locations(statement)
        return statements

    def _rewrite_truth(
        self, node: ast.Assert, test: ast.expr, msg_expr: ast.expr
    ) -> ast.stmt:
        source = self._source_as_written(test)
        raise_stmt = ast.Raise(
            exc=ast.Call(
                func=ast.Name(id="AssertionError", ctx=ast.Load()),
                args=[
                    ast.Call(
                        func=ast.Name(id=_FORMAT_TRUTH, ctx=ast.Load()),
                        args=[ast.Constant(value=source), msg_expr],
                        keywords=[],
                    )
                ],
                keywords=[],
            ),
            cause=None,
        )
        check = ast.If(
            test=ast.UnaryOp(op=ast.Not(), operand=test),
            body=[raise_stmt],
            orelse=[],
        )
        ast.copy_location(check, node)
        ast.fix_missing_locations(check)
        return check


def rewrite_asserts(tree: ast.Module, *, source: str) -> ast.Module:
    """
    Rewrite asserts in a parsed test module and inject the formatters.
    `source` is the text `tree` was parsed from.
    """
    tree = _AssertRewriter(source).visit(tree)

    # Inject the formatter imports after any docstring and __future__ imports.
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

    formatter_import = ast.ImportFrom(
        module="plain.testing.assertions",
        names=[
            ast.alias(name="format_compare", asname=_FORMAT_COMPARE),
            ast.alias(name="format_truth", asname=_FORMAT_TRUTH),
        ],
        level=0,
    )
    # Locate just the injected node — the rewritten asserts already carry
    # locations, so a whole-tree fix_missing_locations pass isn't needed.
    if tree.body:
        ast.copy_location(formatter_import, tree.body[0])
    ast.fix_missing_locations(formatter_import)
    tree.body.insert(insert_at, formatter_import)
    return tree
