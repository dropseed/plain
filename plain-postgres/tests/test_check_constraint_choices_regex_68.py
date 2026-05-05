"""Regression test for issue #68.

A CheckConstraint whose Q references a field that has been excluded from
``against`` (e.g. because ``clean_fields`` already produced a choices
``ValidationError`` for it and ``full_clean`` adds it to ``exclude``)
must not crash with an ``AssertionError`` from inside ``Q.check()``.
The existing ``except FieldError`` branch in ``CheckConstraint.validate``
should swallow the unresolvable lookup, matching the historical behavior.
"""

from __future__ import annotations

from app.examples.models.constraints import ConstraintExample

from plain.postgres import CheckConstraint, Q


def test_check_constraint_validate_skips_when_field_excluded(db: None) -> None:
    """Q references the excluded field 'name' — Q.check() must not assert."""
    constraint = CheckConstraint(
        check=Q(name__regex=r"^ok-(a|b)$"),
        name="name_regex_excluded_field",
    )
    instance = ConstraintExample(name="bogus", description="d")

    # Excluding the constrained field exercises the path where ``against``
    # is missing the alias the Q references. Pre-fix, this crashed with
    # ``AssertionError: Field lookups require a model``. Post-fix, the
    # ``FieldError`` is caught and validate() returns silently.
    constraint.validate(ConstraintExample, instance, exclude={"name"})
