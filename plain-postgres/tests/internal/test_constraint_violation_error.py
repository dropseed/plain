"""Tests for the `violation_error` kwarg on CheckConstraint and
UniqueConstraint, plus the full_clean() / save() integration that surfaces
constraint errors."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from app.examples.models.constraints import ConstraintExample

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.postgres import CheckConstraint, Q, UniqueConstraint
from plain.postgres.constraints import BaseConstraint
from plain.postgres.expressions import F
from plain.postgres.forms import ModelForm
from plain.test import RequestFactory


def _check_constraint() -> CheckConstraint:
    return CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="constraint_must_start_ok",
        violation_error=ValidationError(
            'Name must start with "ok-".', code="bad_prefix"
        ),
    )


def _add_check_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, _check_constraint()),
    )


def test_validate_uses_violation_error(db: None) -> None:
    constraint = _check_constraint()
    instance = ConstraintExample(name="bad", description="d")

    with pytest.raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)

    err = exc_info.value.error_list[0]
    assert err.message == 'Name must start with "ok-".'
    assert err.code == "bad_prefix"


def test_validate_string_violation_error(db: None) -> None:
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="c",
        violation_error="bad name",
    )
    instance = ConstraintExample(name="bad", description="d")
    with pytest.raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)
    assert exc_info.value.messages == ["bad name"]


def test_validate_default_violation_error(db: None) -> None:
    constraint = CheckConstraint(check=Q(name__startswith="ok-"), name="my_constraint")
    instance = ConstraintExample(name="bad", description="d")
    with pytest.raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)
    assert exc_info.value.messages == ['Constraint "my_constraint" is violated.']


def test_validate_passes_when_check_satisfied(db: None) -> None:
    constraint = _check_constraint()
    instance = ConstraintExample(name="ok-fine", description="d")
    constraint.validate(ConstraintExample, instance)


@pytest.mark.parametrize(
    "check",
    [
        Q(name__regex=r"^ok-"),
        Q(name__in=["ok-1", "ok-2"]),
        Q(name="ok-1") | Q(name="ok-2"),
        Q(name__startswith="ok-"),
        Q(name=F("description")),
    ],
)
def test_validate_skips_when_referenced_field_excluded(db: None, check: Q) -> None:
    """If a field referenced by the check expression was excluded (because
    its own field-level validation already failed in full_clean), the
    constraint check is skipped — its annotation isn't in the in-memory
    value map, and surfacing a violation here would just duplicate the
    earlier field error."""
    constraint = CheckConstraint(check=check, name="c")
    instance = ConstraintExample(name="bad", description="d")
    constraint.validate(ConstraintExample, instance, exclude={"name"})


def test_full_clean_runs_constraint_validation(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_check_constraint(monkeypatch)
    instance = ConstraintExample(name="bad", description="d")
    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()
    assert any("Name must start" in m for m in exc_info.value.messages)


def test_full_clean_with_choices_and_check_constraint(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for #68: a CheckConstraint that references a field with
    `choices=` shouldn't crash full_clean when the value fails the choices
    validator. The choice-validator error excludes the field, then the
    constraint check would previously hit `assert self.model is not None`
    in solve_lookup_type."""
    _add_check_constraint(monkeypatch)

    name_field = ConstraintExample._model_meta.get_field("name")
    monkeypatch.setattr(name_field, "choices", [("ok-one", "One"), ("ok-two", "Two")])

    instance = ConstraintExample(name="bogus", description="d")
    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()
    # Choice validator surfaces the field-level error; constraint check is
    # skipped (don't double-report).
    assert "name" in exc_info.value.error_dict


def test_save_runs_full_clean_by_default(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_check_constraint(monkeypatch)
    with pytest.raises(ValidationError):
        ConstraintExample(name="bad", description="d").save()
    assert ConstraintExample.query.filter(name="bad").count() == 0


def test_save_clean_and_validate_false_skips_validation(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_check_constraint(monkeypatch)
    ConstraintExample(name="bad", description="d").save(clean_and_validate=False)
    assert ConstraintExample.query.filter(name="bad").count() == 1


def test_check_constraint_dict_violation_error_routes_to_field(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dict-form violation_error attaches the error to the named field."""
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="must_start_ok",
        violation_error={"name": 'Name must start with "ok-".'},
    )
    monkeypatch.setattr(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, constraint),
    )

    class Form(ModelForm):
        class Meta:
            model = ConstraintExample
            fields = ["name", "description"]

    rf = RequestFactory()
    form = Form(request=rf.post("/x/", data={"name": "bad", "description": "d"}))
    assert not form.is_valid()
    assert form.errors.get("name"), form.errors
    assert "name" in form.errors
    assert "__all__" not in form.errors


def test_check_constraint_string_violation_error_lands_on_non_field_errors(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A bare string violation_error on CheckConstraint goes to NON_FIELD_ERRORS
    because the constraint can't infer which field to attach to from a Q
    expression."""
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="must_start_ok",
        violation_error='Name must start with "ok-".',
    )
    monkeypatch.setattr(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, constraint),
    )

    class Form(ModelForm):
        class Meta:
            model = ConstraintExample
            fields = ["name", "description"]

    rf = RequestFactory()
    form = Form(request=rf.post("/x/", data={"name": "bad", "description": "d"}))
    assert not form.is_valid()
    assert "name" not in form.errors
    assert "__all__" in form.errors


def test_unique_constraint_explicit_validation_error_dict_preserved(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-built ValidationError with an error_dict declares its own
    field routing — single-field auto-routing must not flatten it back under
    the constrained field."""
    constraint = UniqueConstraint(
        fields=["name"],
        name="unique_name_explicit",
        violation_error=ValidationError(
            {"description": "Pick a different name to free this description."}
        ),
    )
    monkeypatch.setattr(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, constraint),
    )

    ConstraintExample(name="dup", description="d1").save(clean_and_validate=False)
    instance = ConstraintExample(name="dup", description="d2")

    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()

    err = exc_info.value
    assert hasattr(err, "error_dict")
    assert "description" in err.error_dict
    assert "name" not in err.error_dict


def test_unique_constraint_single_field_string_routes_to_field(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single-field UniqueConstraint auto-routes a string violation_error to
    that field (no special routing in validate_constraints — the dict-form is
    built inside validate())."""
    constraint = UniqueConstraint(
        fields=["name"],
        name="unique_name_only",
        violation_error="That name is taken.",
    )
    monkeypatch.setattr(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, constraint),
    )

    ConstraintExample(name="dup", description="d1").save(clean_and_validate=False)

    class Form(ModelForm):
        class Meta:
            model = ConstraintExample
            fields = ["name", "description"]

    rf = RequestFactory()
    form = Form(request=rf.post("/x/", data={"name": "dup", "description": "d2"}))
    assert not form.is_valid()
    assert any("That name is taken." in m for m in form.errors.get("name", [])), (
        form.errors
    )


# MARK: IntegrityError -> ValidationError mapping (registry + mapper)


def test_constraints_by_name_registry(db: None) -> None:
    """The Meta registry keys each declared constraint by the name Postgres
    reports in err.diag.constraint_name."""
    registry = ConstraintExample._model_meta.constraints_by_name
    constraint = registry["unique_constraintexample_name_description"]
    assert isinstance(constraint, UniqueConstraint)
    assert constraint.name == "unique_constraintexample_name_description"


def test_mapper_builds_validation_error_for_known_constraint(db: None) -> None:
    instance = ConstraintExample(name="x", description="y")
    exc = SimpleNamespace(
        diag=SimpleNamespace(
            constraint_name="unique_constraintexample_name_description"
        )
    )
    error = instance._integrity_error_to_validation_error(exc)  # ty: ignore[invalid-argument-type]
    assert isinstance(error, ValidationError)
    # Composite unique normalizes to dict form under NON_FIELD_ERRORS, matching
    # validate_constraints() rather than returning a flat error.
    assert NON_FIELD_ERRORS in error.error_dict


def test_mapper_returns_none_for_unknown_constraint(db: None) -> None:
    """A violation whose constraint isn't a declared unique/check constraint
    (a PK collision, an FK violation) is left for the caller — the mapper
    returns None so save_base re-raises the original IntegrityError."""
    instance = ConstraintExample(name="x", description="y")
    exc = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="constraintexample_pkey")
    )
    assert instance._integrity_error_to_validation_error(exc) is None  # ty: ignore[invalid-argument-type]


def test_mapper_returns_none_without_constraint_name(db: None) -> None:
    instance = ConstraintExample(name="x", description="y")
    exc = SimpleNamespace(diag=SimpleNamespace(constraint_name=None))
    assert instance._integrity_error_to_validation_error(exc) is None  # ty: ignore[invalid-argument-type]


def test_base_constraint_db_violation_error_defaults_to_none(db: None) -> None:
    """The polymorphic hook returns None by default, so a constraint type that
    doesn't describe its own DB violations leaves the original IntegrityError to
    propagate rather than silently swallowing it."""
    instance = ConstraintExample(name="x", description="y")
    constraint = BaseConstraint(name="some_constraint")
    assert constraint._db_violation_error(instance, ConstraintExample) is None
