"""`postgres.sql_template_not_literal` — the literal-template rule.

A template or a fragment built at runtime is indistinguishable from a literal
once it's a `str`, so the rule is enforced by reading the source. The fixtures
next door are the two sides of it.
"""

from __future__ import annotations

from pathlib import Path

from plain.postgres.preflight.written import (
    CheckSqlTemplateNotLiteral,
    _built_sql_calls,
)

FIXTURES = Path(__file__).parent / "written_fixtures"


def _flagged(name: str) -> list[tuple[int, str]]:
    path = FIXTURES / name
    return _built_sql_calls(path.read_text(), path)


def test_literal_templates_and_fragments_pass():
    assert _flagged("literal_templates.py") == []


def test_built_templates_and_fragments_are_flagged():
    flagged = _flagged("built_templates.py")
    assert [called for _, called in flagged] == [
        "sql",  # f-string
        "sql",  # concatenation
        "sql",  # a variable
        "sql",  # template= a variable
        "Fragment",  # a variable
        "Fragment",  # text= a variable
        "Fragment",  # `x or ""`
    ]


def test_the_check_runs_clean_on_the_test_app():
    assert CheckSqlTemplateNotLiteral().run() == []
