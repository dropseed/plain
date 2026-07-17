"""Tests for the `violation_error` kwarg on CheckConstraint and
UniqueConstraint, plus the full_clean() / save() integration that surfaces
constraint errors."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from app.examples.models.constraints import ConstraintExample

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.postgres import CheckConstraint, Q, UniqueConstraint
from plain.postgres.constraints import BaseConstraint
from plain.postgres.expressions import F
from plain.postgres.forms import ModelForm
from plain.postgres.test import capture_queries
from plain.test import RequestFactory, cases, patch, raises


def _check_constraint() -> CheckConstraint:
    return CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="constraint_must_start_ok",
        violation_error=ValidationError(
            'Name must start with "ok-".', code="bad_prefix"
        ),
    )


@contextmanager
def _added_constraint(constraint: BaseConstraint):
    with patch(
        ConstraintExample.model_options,
        "constraints",
        (*ConstraintExample.model_options.constraints, constraint),
    ):
        yield


def _add_check_constraint():
    return _added_constraint(_check_constraint())


def test_validate_uses_violation_error() -> None:
    constraint = _check_constraint()
    instance = ConstraintExample(name="bad", description="d")

    with raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)

    err = exc_info.exception.error_list[0]
    assert err.message == 'Name must start with "ok-".'
    assert err.code == "bad_prefix"


def test_validate_string_violation_error() -> None:
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="c",
        violation_error="bad name",
    )
    instance = ConstraintExample(name="bad", description="d")
    with raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)
    assert exc_info.exception.messages == ["bad name"]


def test_validate_default_violation_error() -> None:
    constraint = CheckConstraint(check=Q(name__startswith="ok-"), name="my_constraint")
    instance = ConstraintExample(name="bad", description="d")
    with raises(ValidationError) as exc_info:
        constraint.validate(ConstraintExample, instance)
    assert exc_info.exception.messages == ['Constraint "my_constraint" is violated.']


def test_validate_passes_when_check_satisfied() -> None:
    constraint = _check_constraint()
    instance = ConstraintExample(name="ok-fine", description="d")
    constraint.validate(ConstraintExample, instance)


@cases(
    Q(name__regex=r"^ok-"),
    Q(name__in=["ok-1", "ok-2"]),
    Q(name="ok-1") | Q(name="ok-2"),
    Q(name__startswith="ok-"),
    Q(name=F("description")),
)
def test_validate_skips_when_referenced_field_excluded(check: Q) -> None:
    """If a field referenced by the check expression was excluded (because
    its own field-level validation already failed in full_clean), the
    constraint check is skipped — its annotation isn't in the in-memory
    value map, and surfacing a violation here would just duplicate the
    earlier field error."""
    constraint = CheckConstraint(check=check, name="c")
    instance = ConstraintExample(name="bad", description="d")
    constraint.validate(ConstraintExample, instance, exclude={"name"})


def test_validate_constraints_runs_check_constraints() -> None:
    with _add_check_constraint():
        instance = ConstraintExample(name="bad", description="d")
        with raises(ValidationError) as exc_info:
            instance.validate_constraints()
        assert any("Name must start" in m for m in exc_info.exception.messages)


def test_check_constraint_skipped_for_field_that_failed_shape() -> None:
    """Regression for #68: a CheckConstraint that references a field which
    failed shape validation must be skipped, not validated against the bad
    value (which crashed solve_lookup_type's `assert self.model is not None`).
    full_clean surfaces the choice error; a caller running constraints afterward
    excludes the failed field (as the form does via _get_validation_exclusions),
    so validate_constraints skips the constraint instead of crashing."""
    name_field = ConstraintExample._model_meta.get_field("name")
    with (
        _add_check_constraint(),
        patch(name_field, "choices", [("ok-one", "One"), ("ok-two", "Two")]),
    ):
        instance = ConstraintExample(name="bogus", description="d")
        with raises(ValidationError) as exc_info:
            instance.full_clean()
        assert "name" in exc_info.exception.error_dict

        # The field failed shape validation, so a caller excludes it before the
        # constraint pre-check -- the check constraint over `name` is skipped rather
        # than crashing on the invalid value.
        instance.validate_constraints(exclude={"name"})


def test_form_skips_check_constraint_over_shape_failed_field() -> None:
    """Regression for #68 through the path that actually triggers it -- the form
    auto-deriving the exclusion, not a hand-fed one. A CheckConstraint over a
    field whose submitted value fails shape validation must not be checked
    against the bad value (which crashed solve_lookup_type's
    `assert self.model is not None`). _post_clean records the shape error, then
    recomputes _get_validation_exclusions() -- which reads self._errors -- before
    the constraint pre-check, so the failed field is excluded automatically. The
    form surfaces the shape error and doesn't crash. If that wiring breaks, the
    constraint runs against the bad value and is_valid() raises instead of
    returning False."""
    name_field = ConstraintExample._model_meta.get_field("name")
    with (
        _add_check_constraint(),
        patch(name_field, "choices", [("ok-one", "One"), ("ok-two", "Two")]),
    ):

        class Form(ModelForm):
            class Meta:
                model = ConstraintExample
                fields = ["name", "description"]

        rf = RequestFactory()
        form = Form(
            request=rf.post("/x/", form_data={"name": "bogus", "description": "d"})
        )
        assert not form.is_valid()
        assert "name" in form.errors


def test_save_runs_full_clean_by_default() -> None:
    # save() still runs full_clean's field validation by default. Constraints
    # are no longer pre-checked on save (the DB enforces those — see
    # public/test_integrity_error_mapping); a choices validator is pure-Python,
    # so it's a clean probe that the field-validation half of full_clean runs.
    name_field = ConstraintExample._model_meta.get_field("name")
    with patch(name_field, "choices", [("ok", "OK")]):
        with raises(ValidationError):
            ConstraintExample(name="bad", description="d").create()
        assert ConstraintExample.query.filter(name="bad").count() == 0


def test_save_skips_constraint_pre_check_select() -> None:
    """A default save() issues only the INSERT — the per-unique-constraint
    pre-check SELECT is gone. The database enforces the constraint and
    save_base maps any violation."""
    with capture_queries() as queries:
        ConstraintExample(name="solo", description="row").create()
    assert len(queries) == 1, [q["sql"] for q in queries]


def test_save_clean_and_validate_false_skips_validation() -> None:
    with _add_check_constraint():
        ConstraintExample(name="bad", description="d").create(clean_and_validate=False)
        assert ConstraintExample.query.filter(name="bad").count() == 1


def test_check_constraint_dict_violation_error_routes_to_field() -> None:
    """Dict-form violation_error attaches the error to the named field."""
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="must_start_ok",
        violation_error={"name": 'Name must start with "ok-".'},
    )
    with _added_constraint(constraint):

        class Form(ModelForm):
            class Meta:
                model = ConstraintExample
                fields = ["name", "description"]

        rf = RequestFactory()
        form = Form(
            request=rf.post("/x/", form_data={"name": "bad", "description": "d"})
        )
        assert not form.is_valid()
        assert form.errors.get("name"), form.errors
        assert "name" in form.errors
        assert "__all__" not in form.errors


def test_check_constraint_string_violation_error_lands_on_non_field_errors() -> None:
    """A bare string violation_error on CheckConstraint goes to NON_FIELD_ERRORS
    because the constraint can't infer which field to attach to from a Q
    expression."""
    constraint = CheckConstraint(
        check=Q(name__startswith="ok-"),
        name="must_start_ok",
        violation_error='Name must start with "ok-".',
    )
    with _added_constraint(constraint):

        class Form(ModelForm):
            class Meta:
                model = ConstraintExample
                fields = ["name", "description"]

        rf = RequestFactory()
        form = Form(
            request=rf.post("/x/", form_data={"name": "bad", "description": "d"})
        )
        assert not form.is_valid()
        assert "name" not in form.errors
        assert "__all__" in form.errors


def test_unique_constraint_explicit_validation_error_dict_preserved() -> None:
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
    with _added_constraint(constraint):
        ConstraintExample(name="dup", description="d1").create(clean_and_validate=False)
        instance = ConstraintExample(name="dup", description="d2")

        with raises(ValidationError) as exc_info:
            instance.validate_constraints()

        err = exc_info.exception
        assert hasattr(err, "error_dict")
        assert "description" in err.error_dict
        assert "name" not in err.error_dict


def test_unique_constraint_single_field_string_routes_to_field() -> None:
    """Single-field UniqueConstraint auto-routes a string violation_error to
    that field (no special routing in validate_constraints — the dict-form is
    built inside validate())."""
    constraint = UniqueConstraint(
        fields=["name"],
        name="unique_name_only",
        violation_error="That name is taken.",
    )
    with _added_constraint(constraint):
        ConstraintExample(name="dup", description="d1").create(clean_and_validate=False)

        class Form(ModelForm):
            class Meta:
                model = ConstraintExample
                fields = ["name", "description"]

        rf = RequestFactory()
        form = Form(
            request=rf.post("/x/", form_data={"name": "dup", "description": "d2"})
        )
        assert not form.is_valid()
        assert any("That name is taken." in m for m in form.errors.get("name", [])), (
            form.errors
        )


# MARK: IntegrityError -> ValidationError mapping (registry + mapper)


def test_constraints_by_name_registry() -> None:
    """The Meta registry keys each declared constraint by the name Postgres
    reports in err.diag.constraint_name."""
    registry = ConstraintExample._model_meta.constraints_by_name
    constraint = registry["unique_constraintexample_name_description"]
    assert isinstance(constraint, UniqueConstraint)
    assert constraint.name == "unique_constraintexample_name_description"


def test_mapper_builds_validation_error_for_known_constraint() -> None:
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


def test_mapper_builds_validation_error_for_check_constraint() -> None:
    # Covers the mapper's CheckConstraint branch (the unique branch is above).
    # No check constraint exists in the DB here, so drive the mapper directly
    # with a synthetic diag name pointing at the patched-in check constraint.
    with _add_check_constraint():
        instance = ConstraintExample(name="bad", description="d")
        exc = SimpleNamespace(
            diag=SimpleNamespace(constraint_name="constraint_must_start_ok")
        )
        error = instance._integrity_error_to_validation_error(exc)  # ty: ignore[invalid-argument-type]
        assert isinstance(error, ValidationError)
        assert error.messages == ['Name must start with "ok-".']
        assert NON_FIELD_ERRORS in error.error_dict


def test_mapper_returns_none_for_unknown_constraint() -> None:
    """A violation whose constraint isn't a declared unique/check constraint
    (a PK collision, an FK violation) is left for the caller — the mapper
    returns None so save_base re-raises the original IntegrityError."""
    instance = ConstraintExample(name="x", description="y")
    exc = SimpleNamespace(
        diag=SimpleNamespace(constraint_name="constraintexample_pkey")
    )
    assert instance._integrity_error_to_validation_error(exc) is None  # ty: ignore[invalid-argument-type]


def test_mapper_returns_none_without_constraint_name() -> None:
    instance = ConstraintExample(name="x", description="y")
    exc = SimpleNamespace(diag=SimpleNamespace(constraint_name=None))
    assert instance._integrity_error_to_validation_error(exc) is None  # ty: ignore[invalid-argument-type]


def test_base_constraint_db_violation_error_defaults_to_none() -> None:
    """The polymorphic hook returns None by default, so a constraint type that
    doesn't describe its own DB violations leaves the original IntegrityError to
    propagate rather than silently swallowing it."""
    instance = ConstraintExample(name="x", description="y")
    constraint = BaseConstraint(name="some_constraint")
    assert constraint._db_violation_error(instance, ConstraintExample) is None
