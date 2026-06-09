"""Unit tests for `_collect_model_indexes` — the helper that feeds
`postgres.duplicate_indexes`. Partial indexes/constraints must be
excluded so the check doesn't contradict `postgres.missing_fk_indexes`,
which already treats partials as non-covering.
"""

from __future__ import annotations

from types import SimpleNamespace

from plain.postgres import Q
from plain.postgres.constraints import UniqueConstraint
from plain.postgres.indexes import Index
from plain.postgres.preflight.indexes import _collect_model_indexes


def _model(*, indexes=(), constraints=()) -> SimpleNamespace:
    """Minimal model_options stand-in for the helper."""
    return SimpleNamespace(
        model_options=SimpleNamespace(
            indexes=list(indexes), constraints=list(constraints)
        )
    )


def _names(collected) -> set[str]:
    return {name for name, _fields, _unique in collected}


def test_non_partial_index_collected():
    model = _model(indexes=[Index(name="t_team_idx", fields=["team"])])
    assert _names(_collect_model_indexes(model)) == {"t_team_idx"}


def test_non_partial_unique_constraint_collected():
    model = _model(constraints=[UniqueConstraint(fields=["team"], name="t_team_uniq")])
    assert _names(_collect_model_indexes(model)) == {"t_team_uniq"}


def test_partial_index_excluded():
    model = _model(
        indexes=[
            Index(
                name="t_team_open_idx",
                fields=["team", "created_at"],
                condition=Q(resolved_at__isnull=True),
            )
        ]
    )
    assert _collect_model_indexes(model) == []


def test_partial_unique_constraint_excluded():
    model = _model(
        constraints=[
            UniqueConstraint(
                fields=["team"],
                name="t_team_active_uniq",
                condition=Q(deleted_at__isnull=True),
            )
        ]
    )
    assert _collect_model_indexes(model) == []


def test_bare_index_not_flagged_against_partial_prefix():
    """A bare `Index(fields=[fk])` carried for FK coverage must survive
    alongside a partial composite `Index(fields=[fk, other], condition=...)`
    — otherwise the duplicate check fights the missing-FK check."""
    model = _model(
        indexes=[
            Index(name="t_team_idx", fields=["team"]),
            Index(
                name="t_team_open_idx",
                fields=["team", "created_at"],
                condition=Q(resolved_at__isnull=True),
            ),
        ]
    )
    assert _names(_collect_model_indexes(model)) == {"t_team_idx"}


def test_mixed_keeps_only_non_partial():
    model = _model(
        indexes=[
            Index(name="t_a_idx", fields=["a"]),
            Index(
                name="t_a_partial_idx",
                fields=["a"],
                condition=Q(deleted_at__isnull=True),
            ),
        ],
        constraints=[
            UniqueConstraint(fields=["b"], name="t_b_uniq"),
            UniqueConstraint(
                fields=["b"],
                name="t_b_active_uniq",
                condition=Q(deleted_at__isnull=True),
            ),
        ],
    )
    assert _names(_collect_model_indexes(model)) == {"t_a_idx", "t_b_uniq"}
