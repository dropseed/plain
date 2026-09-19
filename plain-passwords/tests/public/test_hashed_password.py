"""`HashedPassword` — the only form a password takes outside the form layer.

The invariant these pin: a raw password cannot reach the database. It is a
type error at the call site and a `TypeError` at write time, and the
column's own constructor requires the field, so there is no "forgot to set
it" path either.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

import pytest
from app.users.models import User
from plain.exceptions import ValidationError
from plain.passwords.forms import NewPasswordField
from plain.passwords.validators import validate_raw_password
from plain.passwords.values import HashedPassword
from plain.postgres import Field

RAW = "sunflower-old-1"

if TYPE_CHECKING:
    # Checked by `uv run ty check`, not pytest: the column carries a
    # `HashedPassword`, so nothing downstream of the form can see a `str`.
    def _password_is_a_hashed_password(user: User) -> None:
        assert_type(user.password, HashedPassword)
        assert_type(User.password, Field[HashedPassword])


class TestValueType:
    def test_from_raw_hashes(self):
        password = HashedPassword.from_raw(RAW)

        assert str(password) != RAW
        assert password.check(RAW)
        assert not password.check("something-else-3")

    def test_from_raw_salts_each_hash(self):
        assert HashedPassword.from_raw(RAW) != HashedPassword.from_raw(RAW)

    def test_round_trips_through_the_column(self, db):
        user = User.query.create(
            email="rt@example.com", password=HashedPassword.from_raw(RAW)
        )

        reloaded = User.query.get(id=user.id)
        assert isinstance(reloaded.password, HashedPassword)
        assert reloaded.password.check(RAW)
        assert reloaded.password == user.password

    def test_repr_does_not_leak_the_hash(self):
        password = HashedPassword.from_raw(RAW)

        assert repr(password) == "<HashedPassword>"
        assert str(password) not in repr(password)

    def test_a_fresh_hash_does_not_need_rehashing(self):
        assert not HashedPassword.from_raw(RAW).needs_rehash()

    def test_an_unidentifiable_hash_needs_rehashing(self):
        assert HashedPassword("not-an-encoded-hash").needs_rehash()


class TestRawPasswordsAreRefused:
    def test_assigning_a_raw_string_fails_at_write_time(self, db):
        user = User.query.create(
            email="raw@example.com", password=HashedPassword.from_raw(RAW)
        )

        user.password = RAW  # ty: ignore[invalid-assignment]
        with pytest.raises(TypeError, match="takes a HashedPassword, not a str"):
            user.update()

    def test_a_queryset_update_with_a_raw_string_is_refused(self, db):
        User.query.create(email="qs@example.com", password=HashedPassword.from_raw(RAW))

        with pytest.raises(TypeError, match="takes a HashedPassword, not a str"):
            User.query.update(password=RAW)

    def test_filtering_by_a_raw_string_is_refused(self, db):
        with pytest.raises(TypeError, match="takes a HashedPassword, not a str"):
            list(User.query.filter(password=RAW))

    def test_password_is_required_in_the_constructor(self, db):
        """The static half is the `ty: ignore`: `password` is a core-field
        declaration now, so the type checker requires it. If that ever
        regressed, ty would report the suppression as unused and fail the
        build — which is exactly what `PasswordField` could not do."""
        user = User(email="nopw@example.com")  # ty: ignore[missing-argument]

        with pytest.raises(ValidationError, match="cannot be null"):
            user.create()


class TestRawPasswordValidation:
    def test_a_good_password_passes(self):
        validate_raw_password(RAW)

    @pytest.mark.parametrize(
        ("raw", "code"),
        [
            ("short1", "password_too_short"),
            ("password", "password_too_common"),
            ("47238947298", "password_entirely_numeric"),
        ],
    )
    def test_each_rule_reports_its_own_code(self, raw, code):
        with pytest.raises(ValidationError) as exc_info:
            validate_raw_password(raw)

        assert code in {error.code for error in exc_info.value.error_list}

    def test_the_form_field_validates_then_hashes(self):
        field = NewPasswordField()

        cleaned = field.clean(RAW)

        assert isinstance(cleaned, HashedPassword)
        assert cleaned.check(RAW)

    def test_the_form_field_refuses_a_password_that_breaks_a_rule(self):
        field = NewPasswordField()

        with pytest.raises(ValidationError):
            field.clean("short1")
