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


def test_add_not_null_field_without_default_raises() -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            ("name", types.TextField(max_length=100)),
            ("status", types.TextField(max_length=50)),
        ],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value)
    assert "thing.status" in msg.lower()
    assert "default" in msg.lower()


def test_add_not_null_field_with_default_succeeds() -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            ("name", types.TextField(max_length=100)),
            ("status", types.TextField(max_length=50, default="active")),
        ],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    changes = autodetector._detect_changes()
    assert "examples" in changes
    operations = [
        op for migration in changes["examples"] for op in migration.operations
    ]
    assert any(
        op.__class__.__name__ == "AddField" and op.name == "status" for op in operations
    )


def test_add_nullable_field_without_default_succeeds() -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],  # ty: ignore[invalid-argument-type]
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            ("name", types.TextField(max_length=100)),
            (
                "status",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    changes = autodetector._detect_changes()
    assert "examples" in changes


def test_create_model_with_not_null_field_no_default_succeeds() -> None:
    """Brand-new models have no existing rows, so NOT NULL + no default
    is fine — CreateModel handles it without a backfill."""
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            ("id", types.PrimaryKeyField()),
            ("status", types.TextField(max_length=50)),
        ],
    )
    autodetector = MigrationAutodetector(ProjectState(), _state_with(to_model))
    changes = autodetector._detect_changes()
    assert "examples" in changes
    operations = [
        op for migration in changes["examples"] for op in migration.operations
    ]
    assert any(op.__class__.__name__ == "CreateModel" for op in operations)


def test_alter_nullable_to_not_null_without_default_raises() -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            (
                "status",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("status", types.TextField(max_length=50))],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value)
    assert "thing.status" in msg.lower()
    assert "NOT NULL" in msg or "not null" in msg.lower()


def test_alter_nullable_to_not_null_with_default_succeeds() -> None:
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[  # ty: ignore[invalid-argument-type]
            (
                "status",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("status", types.TextField(max_length=50, default="active"))],  # ty: ignore[invalid-argument-type]
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    changes = autodetector._detect_changes()
    assert "examples" in changes
