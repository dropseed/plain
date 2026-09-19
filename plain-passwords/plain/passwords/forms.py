from __future__ import annotations

from typing import Any

from app.users.models import User
from plain.forms import Error, Form, types
from plain.forms.fields import EMPTY_VALUES, Field
from plain.postgres.forms import ModelForm, model_field

from .validators import validate_raw_password
from .values import HashedPassword


class NewPasswordField(Field[HashedPassword]):
    """Takes a raw password, validates it, and hands back a `HashedPassword`.

    This is the boundary: the raw string is read here and nowhere past
    here. A form declaring this field yields a `HashedPassword`, which is
    what a `value_type=HashedPassword` column stores.

    Confirmation fields stay raw `types.TextField`s — a second hash of the
    same password has a different salt, so two hashes can never be compared.
    `check()` on the hashed one against the raw one is the comparison.
    """

    def parse(self, value: Any) -> str:
        if value in EMPTY_VALUES:
            return ""
        return str(value)

    def clean(self, value: Any) -> HashedPassword | None:
        raw = self.parse(value)
        if self._is_missing(raw):
            return None
        validate_raw_password(raw)
        return HashedPassword.from_raw(raw)


def _mismatch(field: str) -> list[Error]:
    return [
        Error(
            "The two password fields didn't match.",
            code="password_mismatch",
            field=field,
        )
    ]


class PasswordResetForm(Form):
    email = types.EmailField(max_length=254)


class PasswordSetForm(Form):
    """Lets a user set a password without entering the old one."""

    new_password = NewPasswordField()
    confirm_password = types.TextField(strip=False)

    def check(self) -> list[Error] | None:
        if not self.new_password.check(self.confirm_password):
            return _mismatch("confirm_password")
        return None


class PasswordChangeForm(PasswordSetForm):
    """Lets a user change their password by confirming the old one."""

    current_password = types.TextField(strip=False)


class PasswordLoginForm(Form):
    email = types.EmailField(max_length=150)
    password = types.TextField(strip=False)


class PasswordSignupForm(ModelForm):
    email = model_field(User.email)
    password = NewPasswordField()
    confirm_password = types.TextField(strip=False)

    def check(self) -> list[Error] | None:
        if not self.password.check(self.confirm_password):
            return _mismatch("confirm_password")
        return None
