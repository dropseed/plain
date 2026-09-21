"""`postgres.sql_template_not_literal` — the literal-template rule.

A template or a fragment built at runtime is indistinguishable from a literal
once it's a `str`, so the rule is enforced by reading the source. The fixtures
next door are the two sides of it.

Everything here goes through `CheckSqlTemplateNotLiteral.run()` rather than the
AST helper underneath, because the file-level prefilter is part of the check
and a gate that never opens reports nothing at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plain.postgres.preflight.written import CheckSqlTemplateNotLiteral

FIXTURES = Path(__file__).parent / "written_fixtures"


def _run_over(tmp_path: Path, source: str, monkeypatch: pytest.MonkeyPatch) -> list:
    """Run the whole check over one file, prefilter included."""
    (tmp_path / "written_example.py").write_text(source)
    monkeypatch.setattr(
        "plain.postgres.preflight.written.APP_PATH", tmp_path, raising=True
    )
    return CheckSqlTemplateNotLiteral().run()


def _run_over_fixture(name: str, monkeypatch: pytest.MonkeyPatch) -> list:
    path = FIXTURES / name
    monkeypatch.setattr(
        "plain.postgres.preflight.written.APP_PATH", FIXTURES, raising=True
    )
    return [
        result
        for result in CheckSqlTemplateNotLiteral().run()
        if path.name in str(result.obj)
    ]


def test_literal_templates_and_fragments_pass(monkeypatch):
    assert _run_over_fixture("literal_templates.py", monkeypatch) == []


def test_built_templates_and_fragments_are_flagged(monkeypatch):
    results = _run_over_fixture("built_templates.py", monkeypatch)
    assert len(results) == 13  # every function in the fixture
    assert all(
        result.id == "postgres.sql_template_not_literal" and not result.warning
        for result in results
    )


def test_a_module_constant_says_what_to_do_instead(monkeypatch):
    results = _run_over_fixture("built_templates.py", monkeypatch)
    constant = [
        r for r in results if r.fix.endswith("write the template out at the call site.")
    ]
    assert constant, "a built sql() template should say to inline the literal"
    fragments = [r for r in results if "Fragment" in r.fix]
    assert any("at module level if it is shared" in r.fix for r in fragments)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        # The prefilter has to let these through: there is no word boundary
        # after `sql(`.
        ('Widget.query.sql("SELECT " + user_input)', 1),
        ("Widget.query.sql(\n    user_input,\n)", 1),
        ("Widget.query.sql (\n    user_input,\n)", 1),
        # A name is never a literal at the call site, however it was bound.
        ('T = "SELECT 1"\nWidget.query.sql(T)', 1),
        ('T: str = "SELECT 1"\nWidget.query.sql(T)', 1),
        ("Widget.query.sql(T := source)", 1),
        ("from x import T\nWidget.query.sql(T)", 1),
        # A literal written at the call site is the whole rule.
        ('Widget.query.sql("SELECT 1")', 0),
        ('Widget.query.sql(template="SELECT 1")', 0),
        ('Fragment("size = 1")', 0),
        # Not a queryset's sql().
        ("parsed.sql(dialect)", 0),
        ("self.sql(other)", 0),
        # A queryset reached through a chain still counts.
        ("Widget.query.all().sql(template)", 1),
        ("get_model().query.sql(template)", 1),
    ],
)
def test_the_rules(source, expected, tmp_path, monkeypatch):
    assert len(_run_over(tmp_path, source, monkeypatch)) == expected


def test_the_check_runs_clean_on_the_test_app():
    assert CheckSqlTemplateNotLiteral().run() == []
