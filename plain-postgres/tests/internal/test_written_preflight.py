"""`postgres.sql_template_not_literal` — the literal-template rule.

A template or a fragment built at runtime is indistinguishable from a literal
once it's a `str`, so the rule is enforced by reading the source. The fixtures
next door are the two sides of it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plain.postgres.preflight.written import (
    CheckSqlTemplateNotLiteral,
    _built_sql_calls,
)

FIXTURES = Path(__file__).parent / "written_fixtures"


def _flagged(name: str) -> list[tuple[int, str]]:
    path = FIXTURES / name
    return _built_sql_calls(path.read_text(), path)


def _flag(source: str) -> list[tuple[int, str]]:
    return _built_sql_calls(source, Path("inline.py"))


def test_literal_templates_and_fragments_pass():
    assert _flagged("literal_templates.py") == []


def test_built_templates_and_fragments_are_flagged():
    flagged = _flagged("built_templates.py")
    assert [called for _, called in flagged] == [
        "sql",  # f-string
        "sql",  # concatenation
        "sql",  # a call
        "sql",  # a variable
        "sql",  # template= a variable
        "sql",  # a module name that is rebound
        "sql",  # a module name bound by a for loop
        "Fragment",  # a variable
        "Fragment",  # text= a variable
        "Fragment",  # `x or ""`
        "Fragment",  # through an import alias
        "Written",  # the class directly, template= a variable
    ]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # A module-level literal, bound once and never rebound, is the SQL
        # written in the source one step earlier.
        ('T = "SELECT 1"\nWidget.query.sql(T)', 0),
        ('T: str = "SELECT 1"\nWidget.query.sql(T)', 0),
        # Bound twice at module level: whichever ran last is anyone's guess.
        ('T = "SELECT 1"\nT = "SELECT 2"\nWidget.query.sql(T)', 1),
        # Rebound inside a function, by an augmented assignment, by a `with`,
        # or declared `global` and written to.
        ('T = "SELECT 1"\ndef f():\n    global T\n    T = x\nWidget.query.sql(T)', 1),
        ('T = "SELECT 1"\nT += "x"\nWidget.query.sql(T)', 1),
        ('T = "SELECT 1"\nwith open(p) as T:\n    pass\nWidget.query.sql(T)', 1),
        # Shadowed by a parameter somewhere in the module.
        ('T = "SELECT 1"\ndef f(T):\n    return T\nWidget.query.sql(T)', 1),
        # An imported name is not a literal this module can see.
        ("from x import T\nWidget.query.sql(T)", 1),
        # Not a queryset's sql().
        ("parsed.sql(dialect)", 0),
        ("self.sql(other)", 0),
        # A queryset reached through a chain still counts.
        ("Widget.query.all().sql(template)", 1),
        ("get_model().query.sql(template)", 1),
    ],
)
def test_the_name_rules(source, expected):
    assert len(_flag(source)) == expected


def test_the_check_runs_clean_on_the_test_app():
    assert CheckSqlTemplateNotLiteral().run() == []
