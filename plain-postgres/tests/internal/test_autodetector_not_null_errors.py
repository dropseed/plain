from __future__ import annotations

from typing import Any

import pytest
from plain.postgres import types
from plain.postgres.migrations.autodetector import MigrationAutodetector
from plain.postgres.migrations.exceptions import MigrationSchemaError
from plain.postgres.migrations.questioner import MigrationQuestioner
from plain.postgres.migrations.state import ModelState, ProjectState


def _state_with(model_state: ModelState) -> ProjectState:
    state = ProjectState()
    state.add_model(model_state)
    return state


def _added_field_changes(field: Any) -> dict[str, Any]:
    """Autodetect adding `field` to a model whose table may already have rows."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
            ("name", types.TextField(max_length=100)),
            ("added", field),
        ],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    return autodetector._detect_changes()


@pytest.mark.parametrize(
    "field",
    [
        types.TextField(max_length=50),
        types.TextField(max_length=50, required=False),
        types.EncryptedTextField(required=False),
        types.BinaryField(required=False),
    ],
    ids=["text", "optional-text", "encrypted", "binary"],
)
def test_add_not_null_field_without_default_raises(field: Any) -> None:
    """NOT NULL + no declared default can't backfill existing rows. required=False
    alone is not enough — its Python-side empty-value fill is invisible to the
    schema layer."""
    with pytest.raises(MigrationSchemaError) as exc:
        _added_field_changes(field)
    msg = str(exc.value)
    assert "thing.added" in msg.lower()
    assert "default" in msg.lower()


@pytest.mark.parametrize(
    "field",
    [
        types.TextField(max_length=50, default="active"),
        types.TextField(max_length=50, required=False, default=""),
        types.EncryptedTextField(required=False, default=""),
        types.BinaryField(required=False, default=b""),
        types.TextField(max_length=50, allow_null=True, required=False),
    ],
    ids=[
        "text-default",
        "optional-text-empty",
        "encrypted-empty",
        "binary-empty",
        "nullable",
    ],
)
def test_add_field_with_backfill_succeeds(field: Any) -> None:
    """A declared default (persistent column DEFAULT) or allow_null=True gives
    existing rows a value, so the AddField is generated."""
    changes = _added_field_changes(field)
    operations = [
        op for migration in changes["examples"] for op in migration.operations
    ]
    assert any(
        op.__class__.__name__ == "AddField" and op.name == "added" for op in operations
    )


def test_backfill_error_suggests_the_empty_default_spelling() -> None:
    """For empty-only-default fields the remedy must render the exact working
    declaration — not echo something the user already wrote."""
    with pytest.raises(MigrationSchemaError) as exc:
        _added_field_changes(types.EncryptedTextField())
    msg = str(exc.value)
    assert "types.EncryptedTextField(required=False, default='')" in msg
    assert "Choose one:" in msg


def test_backfill_error_placeholder_is_not_executable() -> None:
    """The general example must say default=<value>, not default=... —
    Ellipsis is valid Python, so a literally-copied `default=...` would
    construct and then persist garbage (e.g. str(Ellipsis) on a TextField)."""
    with pytest.raises(MigrationSchemaError) as exc:
        _added_field_changes(types.IntegerField())
    assert "types.IntegerField(default=<value>)" in str(exc.value)


@pytest.mark.parametrize(
    "field",
    [
        # Not a DefaultableField at all.
        types.DateTimeField(),
        # A DefaultableField whose __init__ deliberately takes no default=
        # (accepts_default=False).
        types.EncryptedJSONField(),
    ],
    ids=["datetime", "encrypted-json"],
)
def test_backfill_error_omits_default_remedy_for_non_defaultable_fields(
    field: Any,
) -> None:
    """Fields with no default= kwarg get only the allow_null remedy —
    suggesting a default would be advice that raises."""
    with pytest.raises(MigrationSchemaError) as exc:
        _added_field_changes(field)
    msg = str(exc.value)
    assert "Fix:" in msg
    assert "Declare a default" not in msg


def test_create_model_with_not_null_field_no_default_succeeds() -> None:
    """Brand-new models have no existing rows, so NOT NULL + no default
    is fine — CreateModel handles it without a backfill."""
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
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


def test_alter_nullable_to_not_null_is_autodetector_no_op() -> None:
    """Nullability is convergence-managed. The autodetector strips non_migration_attrs
    before comparing, so an allow_null-only diff emits no migration —
    convergence picks up NullabilityDrift on the next sync and blocks with
    guidance if NULL rows exist."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
            (
                "status",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("status", types.TextField(max_length=50))],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    assert autodetector._detect_changes() == {}


def test_alter_nullable_to_not_null_with_default_is_autodetector_no_op() -> None:
    """Declaring a default alongside NOT NULL still emits no migration — both
    allow_null and default are non_migration_attrs. Convergence applies the DEFAULT
    and SetNotNullCorrection on the next sync."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
            (
                "status",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("status", types.TextField(max_length=50, default="active"))],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    assert autodetector._detect_changes() == {}


def test_rename_combined_with_null_change_raises() -> None:
    """A proposed rename where the field ALSO flips nullable→NOT NULL is not
    recognized as a rename — deep_deconstruct() differs on allow_null/required,
    so the autodetector treats it as remove+add. The add path then raises for
    the missing backfill, even when the questioner would have accepted the
    rename."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
            (
                "old_name",
                types.TextField(max_length=50, allow_null=True, required=False),
            ),
        ],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("new_name", types.TextField(max_length=50))],
    )
    questioner = MigrationQuestioner(defaults={"ask_rename": True})
    autodetector = MigrationAutodetector(
        _state_with(from_model),
        _state_with(to_model),
        questioner=questioner,
    )
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value).lower()
    assert "thing.new_name" in msg
    assert "default" in msg


def test_multiple_new_fields_without_default_reports_first() -> None:
    """When multiple new NOT NULL fields lack defaults, detection stops on the
    first one (sorted order). The user fixes it, re-runs, and sees the next —
    a batch isn't silently partially-generated."""
    from_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[("name", types.TextField(max_length=100))],
    )
    to_model = ModelState(
        package_label="examples",
        name="Thing",
        fields=[
            ("name", types.TextField(max_length=100)),
            ("a_status", types.TextField(max_length=50)),
            ("z_status", types.TextField(max_length=50)),
        ],
    )
    autodetector = MigrationAutodetector(_state_with(from_model), _state_with(to_model))
    with pytest.raises(MigrationSchemaError) as exc:
        autodetector._detect_changes()
    msg = str(exc.value).lower()
    assert "thing.a_status" in msg
    assert "thing.z_status" not in msg
