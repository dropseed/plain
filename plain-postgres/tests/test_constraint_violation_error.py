"""Tests for the `violation_error` kwarg on CheckConstraint and
UniqueConstraint, plus the full_clean() / save() integration that surfaces
constraint errors."""

from __future__ import annotations

import pytest
from app.examples.models.constraints import ConstraintExample

from plain.exceptions import ValidationError
from plain.postgres import CheckConstraint, Q, UniqueConstraint
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


def test_full_clean_runs_constraint_validation(
    db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_check_constraint(monkeypatch)
    instance = ConstraintExample(name="bad", description="d")
    with pytest.raises(ValidationError) as exc_info:
        instance.full_clean()
    assert any("Name must start" in m for m in exc_info.value.messages)


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
