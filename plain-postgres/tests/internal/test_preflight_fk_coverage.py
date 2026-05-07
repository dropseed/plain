"""Unit tests for `_fk_covered_field_names` — the helper that powers
`postgres.missing_fk_indexes`'s preflight check.

The check fires on FK fields whose name doesn't appear here. The helper
must recognize bare `F("col")` leading expressions so a constraint like
`UniqueConstraint(F("team"), Lower("email"))` counts as covering the
`team` FK — Postgres' underlying btree's leading column is the real
`team` attribute, not an expression.
"""

from __future__ import annotations

from types import SimpleNamespace

from plain.postgres.constraints import UniqueConstraint
from plain.postgres.expressions import F
from plain.postgres.functions import Lower
from plain.postgres.indexes import Index
from plain.postgres.preflight import _fk_covered_field_names


def _model(*, indexes=(), constraints=()) -> SimpleNamespace:
    """Minimal model_options stand-in for the helper."""
    return SimpleNamespace(
        model_options=SimpleNamespace(
            indexes=list(indexes), constraints=list(constraints)
        )
    )


def test_covers_index_with_fields():
    model = _model(indexes=[Index(name="t_team_idx", fields=["team"])])
    assert _fk_covered_field_names(model) == {"team"}


def test_covers_unique_constraint_with_fields():
    model = _model(
        constraints=[
            UniqueConstraint(fields=["team", "account"], name="t_team_acct_uniq")
        ]
    )
    assert _fk_covered_field_names(model) == {"team"}


def test_covers_unique_constraint_with_bare_f_leading_expression():
    """A unique constraint declared via `expressions=` whose leading
    expression is a bare `F("col")` covers the FK — the underlying btree's
    leading attribute is still the real column."""
    model = _model(
        constraints=[
            UniqueConstraint(
                F("team"),
                Lower("email"),
                name="t_team_email_uniq",
            )
        ]
    )
    assert "team" in _fk_covered_field_names(model)


def test_covers_unique_constraint_with_ordered_bare_f_leading_expression():
    """`F("team").desc()` produces `OrderBy(F("team"))`. Postgres still emits
    `team_id DESC` as a real leading column attribute, so equality FK
    lookups are covered (sort direction doesn't matter for `WHERE = ?`)."""
    model = _model(
        constraints=[
            UniqueConstraint(
                F("team").desc(),
                Lower("email"),
                name="t_team_desc_email_uniq",
            )
        ]
    )
    assert "team" in _fk_covered_field_names(model)


def test_does_not_cover_when_leading_expression_is_compound():
    """`(LOWER(email), team)` cannot satisfy `WHERE team = ?` from the
    leading column — the leading "column" is an expression, so Postgres
    can't range-scan it for a value lookup on team."""
    model = _model(
        constraints=[
            UniqueConstraint(
                Lower("email"),
                F("team"),
                name="t_lower_email_team_uniq",
            )
        ]
    )
    assert "team" not in _fk_covered_field_names(model)


def test_strips_descending_prefix_from_field_name():
    """`fields=["-created_at"]` (descending) still has `created_at` as the
    underlying column. The leading-column extraction must strip the prefix."""
    model = _model(indexes=[Index(name="t_created_idx", fields=["-created_at"])])
    assert _fk_covered_field_names(model) == {"created_at"}


def test_unions_indexes_and_constraints():
    model = _model(
        indexes=[Index(name="t_a_idx", fields=["a"])],
        constraints=[
            UniqueConstraint(fields=["b"], name="t_b_uniq"),
            UniqueConstraint(F("c"), Lower("d"), name="t_c_d_uniq"),
        ],
    )
    assert _fk_covered_field_names(model) == {"a", "b", "c"}
