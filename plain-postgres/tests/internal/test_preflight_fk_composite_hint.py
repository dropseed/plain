"""Unit tests for `_composite_containing` — the helper that lets
`postgres.missing_fk_indexes` suggest reordering an existing composite
index instead of adding a new one when the FK sits at a non-leading
position.
"""

from __future__ import annotations

from types import SimpleNamespace

from plain.postgres import Q
from plain.postgres.constraints import UniqueConstraint
from plain.postgres.indexes import Index
from plain.postgres.preflight import _composite_containing


def _model(*, indexes=(), constraints=()) -> SimpleNamespace:
    """Minimal model_options stand-in for the helper."""
    return SimpleNamespace(
        model_options=SimpleNamespace(
            indexes=list(indexes), constraints=list(constraints)
        )
    )


def test_finds_index_with_non_leading_field():
    model = _model(
        indexes=[Index(name="t_type_team_idx", fields=["event_type", "team"])]
    )
    assert _composite_containing(model, "team") == (
        "t_type_team_idx",
        ["event_type", "team"],
    )


def test_finds_unique_constraint_with_non_leading_field():
    model = _model(
        constraints=[
            UniqueConstraint(fields=["event_type", "team"], name="t_type_team_uniq")
        ]
    )
    assert _composite_containing(model, "team") == (
        "t_type_team_uniq",
        ["event_type", "team"],
    )


def test_leading_field_does_not_match():
    """A leading position already covers the FK — no reorder to suggest."""
    model = _model(
        indexes=[Index(name="t_team_type_idx", fields=["team", "event_type"])]
    )
    assert _composite_containing(model, "team") is None


def test_absent_field_does_not_match():
    model = _model(
        indexes=[Index(name="t_type_idx", fields=["event_type", "created_at"])]
    )
    assert _composite_containing(model, "team") is None


def test_partial_index_does_not_match():
    """Partial composites are excluded — they can't cover arbitrary FK
    lookups even after a reorder, so suggesting one would mislead."""
    model = _model(
        indexes=[
            Index(
                name="t_type_team_active_idx",
                fields=["event_type", "team"],
                condition=Q(deleted_at__isnull=True),
            )
        ]
    )
    assert _composite_containing(model, "team") is None


def test_strips_descending_prefix():
    model = _model(
        indexes=[Index(name="t_type_team_idx", fields=["event_type", "-team"])]
    )
    assert _composite_containing(model, "team") == (
        "t_type_team_idx",
        ["event_type", "team"],
    )
