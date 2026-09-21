"""Preflight check: a written query's template is written, not built.

`sql()` interpolates `{}` references and binds every value as a parameter, so
nothing a user typed can reach the SQL text — unless the template itself was
built at runtime. An f-string template, or a `Fragment` made from a variable,
puts that guarantee back in the caller's hands.

Reading the source is the only way to tell: at runtime an f-string is just a
`str`. So this parses the app's Python files and refuses any `sql()` template
or `Fragment`/`Written` text that isn't a string literal **written at the call
site**. A name is never accepted, however it was bound: following one means
tracking every way Python can rebind it — an assignment, a walrus, a
comprehension target, a `match` capture, an `except ... as`, a `def` — and
missing one of them is a false pass on the one thing this check exists for.

Sharing is spelled with a `Fragment`: `ACTIVE = Fragment("status = 'active'")`
at module level is checked where the `Fragment(...)` is written, and passing
`ACTIVE` around afterwards is passing a checked object, not a string. A whole
template is written where it is used.

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
from pathlib import Path

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import APP_PATH

# The rule, stated once and printed with every result.
RULE = (
    "templates and fragments are literals; values go through {name} and bind "
    "as parameters"
)

# What to do instead, which depends on which one was built.
_INSTEAD = {
    "sql": "write the template out at the call site",
    "Fragment": "build the Fragment from a literal, at module level if it is shared",
    "Written": "write the template out at the call site",
}

# Cheap gate before parsing a file at all. `sql(` is matched without a
# trailing word boundary -- there isn't one after `(`.
_MENTIONS = re.compile(r"\bsql\s*\(|\b(?:Fragment|Written)\b")

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
                            f"{where} builds the {called}() template at "
                            f"runtime — {RULE}. Here: "
                            f"{_INSTEAD[called]}."
                        ),
                        obj=where,
                        id="postgres.sql_template_not_literal",
                    )
                )
        return results
