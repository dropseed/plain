"""Preflight check: a written query's template is written, not built.

`sql()` interpolates `{}` references and binds every value as a parameter, so
nothing a user typed can reach the SQL text — unless the template itself was
built at runtime. An f-string template, or a `Fragment` made from a variable,
puts that guarantee back in the caller's hands.

Reading the source is the only way to tell: at runtime an f-string is just a
`str`. So this walks the app's Python files and refuses any `sql()` template or
`Fragment` text that isn't a string literal.
"""

from __future__ import annotations

import ast
from pathlib import Path

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import APP_PATH

# The rule, stated once and printed with every result.
RULE = (
    "templates and fragments are literals; values go through {name} and bind "
    "as parameters"
)


def _relative(path: Path) -> str:
    """The path as the person running preflight would type it."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _called_name(func: ast.expr) -> str | None:
    """The plain name of what's being called: `qs.sql(...)` -> `sql`."""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _argument(call: ast.Call, keyword: str) -> ast.expr | None:
    """The call's first positional argument, or the keyword it can be passed as."""
    if call.args:
        return call.args[0]
    for given in call.keywords:
        if given.arg == keyword:
            return given.value
    return None


def _literal_names(tree: ast.Module) -> set[str]:
    """Module-level names bound to a string literal.

    `ACTIVE = Fragment("status = 'active'")` is the documented way to name a
    fragment, and `TEMPLATE = "SELECT ..."` is the same thing one step earlier:
    the SQL is still written in the source, so passing that name is not a
    built template.
    """
    names = set()
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
    return names


def _built_sql_calls(source: str, path: Path) -> list[tuple[int, str]]:
    """Every `sql()` template and `Fragment()` text in this file that is built.

    Returns `(line number, what was called)` for each one.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Not this check's job to report; the interpreter will.
        return []

    literals = _literal_names(tree)
    built = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node.func)
        if name == "sql":
            argument = _argument(node, "template")
        elif name == "Fragment":
            argument = _argument(node, "text")
        else:
            continue
        if argument is None:
            continue
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            continue
        if isinstance(argument, ast.Name) and argument.id in literals:
            continue
        built.append((node.lineno, name))
    return built


@register_check("postgres.sql_template_not_literal")
class CheckSqlTemplateNotLiteral(PreflightCheck):
    """Refuses a `sql()` template or a `Fragment` built at runtime."""

    def run(self) -> list[PreflightResult]:
        if not APP_PATH.exists():
            return []

        results = []
        for path in sorted(APP_PATH.rglob("*.py")):
            source = path.read_text(encoding="utf-8", errors="replace")
            if "sql(" not in source and "Fragment(" not in source:
                continue
            for line, called in _built_sql_calls(source, path):
                where = f"{_relative(path)}:{line}"
                results.append(
                    PreflightResult(
                        # The location goes in the message: `obj` isn't printed.
                        fix=(
                            f"{where} builds the {called}() template at runtime "
                            f"— {RULE}."
                        ),
                        obj=where,
                        id="postgres.sql_template_not_literal",
                    )
                )
        return results
