"""Preflight check: a written query's template is written, not built.

`sql()` interpolates `{}` references and binds every value as a parameter, so
nothing a user typed can reach the SQL text — unless the template itself was
built at runtime. An f-string template, or a `Fragment` made from a variable,
puts that guarantee back in the caller's hands.

Reading the source is the only way to tell: at runtime an f-string is just a
`str`. So this parses the app's Python files and refuses any `sql()` template
or `Fragment`/`Written` text that isn't a literal.

What it does **not** see:

- Anything outside `APP_PATH`. Installed packages are not scanned; a package
  that writes queries is expected to check its own source.
- A `sql()` call reached some other way than a queryset — the call has to have
  `.query` somewhere in the expression it's called on, so that an unrelated
  object's `.sql(...)` method isn't reported.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Sequence
from pathlib import Path

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import APP_PATH

# The rule, stated once and printed with every result.
RULE = (
    "templates and fragments are literals; values go through {name} and bind "
    "as parameters"
)

# Cheap gate before parsing a file at all.
_MENTIONS = re.compile(r"\b(sql\s*\(|Fragment|Written)\b")

# The written-query constructors whose first argument is SQL text, by the name
# they are defined under. A module's imports are what map a local name back to
# one of these.
_TEXT_ARGUMENT = {
    "plain.postgres.written.Fragment": "text",
    "plain.postgres.written.Written": "template",
}
_IMPORTABLE_FROM = ("plain.postgres", "plain.postgres.written")


def _relative(path: Path) -> str:
    """The path as the person running preflight would type it."""
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _imported_names(tree: ast.Module) -> dict[str, str]:
    """Local name -> the written-query class it refers to.

    Alias-proof: `from plain.postgres import Fragment as F` binds `F`, and
    `import plain.postgres as pg` makes `pg.Fragment` reachable by attribute,
    which `_called_class` handles separately.
    """
    bound = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in _IMPORTABLE_FROM:
            for alias in node.names:
                qualified = f"plain.postgres.written.{alias.name}"
                if qualified in _TEXT_ARGUMENT:
                    bound[alias.asname or alias.name] = qualified
    return bound


def _called_class(call: ast.Call, imported: dict[str, str]) -> str | None:
    """The written-query class this call constructs, if it constructs one."""
    if isinstance(call.func, ast.Name):
        return imported.get(call.func.id)
    if isinstance(call.func, ast.Attribute):
        # `postgres.Fragment(...)` / `written.Fragment(...)`: the attribute
        # name is enough, since nothing else in a Plain app is called that.
        qualified = f"plain.postgres.written.{call.func.attr}"
        return qualified if qualified in _TEXT_ARGUMENT else None
    return None


def _is_queryset_sql(call: ast.Call) -> bool:
    """Whether this is `<something>.query...sql(...)`.

    `sql()` is only reachable through a queryset, so requiring `.query`
    somewhere in the receiver keeps an unrelated `parsed.sql(dialect)` out of
    the results.
    """
    if not isinstance(call.func, ast.Attribute) or call.func.attr != "sql":
        return False
    return any(
        isinstance(node, ast.Attribute) and node.attr == "query"
        for node in ast.walk(call.func.value)
    )


def _argument(call: ast.Call, keyword: str) -> ast.expr | None:
    """The call's first positional argument, or the keyword it can be passed as."""
    if call.args:
        return call.args[0]
    for given in call.keywords:
        if given.arg == keyword:
            return given.value
    return None


def _literal_names(tree: ast.Module) -> set[str]:
    """Module-level names that can only ever be one string literal.

    `TEMPLATE = "SELECT ..."` at module level is the SQL written in the
    source, one step earlier, so passing that name is not a built template.
    The name has to be bound exactly once, at module level, to a literal, and
    never rebound anywhere in the module — a later assignment, an augmented
    assignment, a parameter, a loop variable, a `with ... as`, or a `global`
    write all disqualify it, because then the name is whatever ran last.
    """
    literals: dict[str, int] = {}
    for node in tree.body:
        targets: Sequence[ast.expr] = []
        value: ast.expr | None = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                if isinstance(target, ast.Name):
                    literals[target.id] = literals.get(target.id, 0) + 1

    rebound = _rebound_names(tree)
    return {
        name for name, times in literals.items() if times == 1 and name not in rebound
    }


def _rebound_names(tree: ast.Module) -> set[str]:
    """Every name the module binds somewhere other than one module-level literal."""
    module_level_literals = {
        id(node)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    rebound: set[str] = set()

    def names_in(target: ast.expr) -> list[str]:
        return [
            node.id
            for node in ast.walk(target)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)
        ]

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and id(node) not in module_level_literals:
            for target in node.targets:
                rebound.update(names_in(target))
        elif isinstance(node, ast.AugAssign | ast.AnnAssign):
            if isinstance(node, ast.AugAssign) or not (
                isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                rebound.update(names_in(node.target))
        elif isinstance(node, ast.For | ast.AsyncFor):
            rebound.update(names_in(node.target))
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            rebound.update(names_in(node.optional_vars))
        elif isinstance(node, ast.Global | ast.Nonlocal):
            rebound.update(node.names)
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            arguments = node.args
            rebound.update(
                argument.arg
                for group in (
                    arguments.posonlyargs,
                    arguments.args,
                    arguments.kwonlyargs,
                )
                for argument in group
            )
            for maybe in (arguments.vararg, arguments.kwarg):
                if maybe is not None:
                    rebound.add(maybe.arg)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            rebound.update(
                alias.asname or alias.name.split(".")[0] for alias in node.names
            )

    return rebound


def _built_sql_calls(source: str, path: Path) -> list[tuple[int, str]]:
    """Every SQL text argument in this file that is built rather than written.

    Returns `(line number, what was called)` for each one.
    """
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        # Not this check's job to report; the interpreter will.
        return []

    imported = _imported_names(tree)
    literals = _literal_names(tree)
    built = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if _is_queryset_sql(node):
            called, argument = "sql", _argument(node, "template")
        elif (qualified := _called_class(node, imported)) is not None:
            called = qualified.rsplit(".", 1)[1]
            argument = _argument(node, _TEXT_ARGUMENT[qualified])
        else:
            continue

        if argument is None:
            continue
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            continue
        if isinstance(argument, ast.Name) and argument.id in literals:
            continue
        built.append((node.lineno, called))
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
            if not _MENTIONS.search(source):
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
