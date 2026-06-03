"""A constraint violation that reaches the database — because the in-Python
pre-check was bypassed or raced — surfaces as a ValidationError, the same
error the pre-check would have raised, not a raw psycopg.IntegrityError."""

from __future__ import annotations

import pytest
from app.examples.models.constraints import ConstraintExample

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.postgres import transaction


def test_constraint_violation_reaching_db_raises_validation_error(db: None) -> None:
    # clean_and_validate=False bypasses the in-Python check, so the duplicate
    # reaches the database — the deterministic stand-in for a raced insert.
    ConstraintExample(name="dup", description="same").save(clean_and_validate=False)

    with pytest.raises(ValidationError):
        ConstraintExample(name="dup", description="same").save(clean_and_validate=False)


def test_caught_violation_matches_pre_check_and_recovers_in_atomic(db: None) -> None:
    ConstraintExample(name="dup", description="same").save(clean_and_validate=False)

    # The pre-check (full_clean) raises this for the duplicate...
    with pytest.raises(ValidationError) as pre_check:
        ConstraintExample(name="dup", description="same").full_clean()

    # ...and the database catch raises the same thing when the pre-check is
    # bypassed. Wrapping in atomic() rolls back to a savepoint, so the caller
    # can keep using the transaction after handling the error.
    with pytest.raises(ValidationError) as caught:
        with transaction.atomic():
            ConstraintExample(name="dup", description="same").save(
                clean_and_validate=False
            )

    # Same messages AND same routing: the database catch normalizes to the
    # dict shape validate_constraints() produces, so a composite unique lands
    # under NON_FIELD_ERRORS either way rather than as a flat error.
    assert caught.value.messages == pre_check.value.messages
    assert caught.value.error_dict.keys() == pre_check.value.error_dict.keys()
    assert NON_FIELD_ERRORS in caught.value.error_dict

    # The transaction is usable again after the savepoint rollback, and the
    # duplicate never landed.
    assert ConstraintExample.query.filter(name="dup").count() == 1


def test_default_save_maps_duplicate_to_validation_error(db: None) -> None:
    """A duplicate on the default save() path (validation on) raises
    ValidationError. (That the database does the rejecting rather than a
    pre-check is what test_save_skips_constraint_pre_check_select proves; this
    pins the user-facing contract on the common path.)"""
    ConstraintExample(name="dup", description="same").save()

    with pytest.raises(ValidationError):
        with transaction.atomic():
            ConstraintExample(name="dup", description="same").save()

    assert ConstraintExample.query.filter(name="dup").count() == 1
