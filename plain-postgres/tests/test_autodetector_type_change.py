from __future__ import annotations

import pytest

from plain.postgres import types
from plain.postgres.migrations.autodetector import MigrationAutodetector
from plain.postgres.migrations.exceptions import MigrationSchemaError
from plain.postgres.migrations.state import ModelState, ProjectState


def _state_with(model_state: ModelState) -> ProjectState:
    state = ProjectState()
    state.add_model(model_state)
    return state


def test_base_type_change_raises() -> None:
    """Impossible cast: a timestamp column can't be rewritten as a UUID."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("created_at", types.DateTimeField())],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("created_at", types.UUIDField())],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value)
    assert "thing.created_at" in msg.lower()
    assert "uuid" in msg.lower()
    assert "alter_thing_created_at_type" in msg


def test_parameter_only_change_succeeds() -> None:
    """Same unqualified_db_type (text) — parameter-only diff generates a normal AlterField."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=50))],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    changes = autodetector._detect_changes()
    ops = [op for migration in changes["examples"] for op in migration.operations]
    assert any(
        op.__class__.__name__ == "AlterField" and op.name == "name" for op in ops
    )


@pytest.mark.parametrize(
    ("from_field", "to_field"),
    [
        (types.IntegerField, types.BigIntegerField),
        (types.SmallIntegerField, types.IntegerField),
        (types.SmallIntegerField, types.BigIntegerField),
    ],
)
def test_safe_widening_allowed(from_field, to_field) -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("count", from_field())],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("count", to_field())],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    changes = autodetector._detect_changes()
    ops = [op for migration in changes["examples"] for op in migration.operations]
    assert any(
        op.__class__.__name__ == "AlterField" and op.name == "count" for op in ops
    )


def test_bigint_to_integer_rejected() -> None:
    """Narrowings aren't in the allowlist — Postgres accepts the cast but fails
    at runtime on rows whose value exceeds int32. Force the user into an explicit
    RunSQL so they own that risk."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("count", types.BigIntegerField())],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("count", types.IntegerField())],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value).lower()
    assert "thing.count" in msg
    assert "bigint" in msg
    assert "integer" in msg
