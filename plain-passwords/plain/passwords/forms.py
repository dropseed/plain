from __future__ import annotations

from app.users.models import User

from plain.forms import Error, Field, Form, types
from plain.postgres.forms import ModelForm, model_field


class PasswordResetForm(Form):
    email = types.EmailField(max_length=254)


class PasswordSetForm(Form):
    """Lets a user set a password without entering the old one."""

    new_password1 = types.TextField(strip=False)
    new_password2 = types.TextField(strip=False)

    def check(self) -> list[Error] | None:
        if self.new_password1 != self.new_password2:
            return [
                Error(
                    "The two password fields didn't match.",
                    code="password_mismatch",
                    field="new_password2",
                )
            ]
        return None


class PasswordChangeForm(PasswordSetForm):
    """Lets a user change their password by confirming the old one."""

    current_password = types.TextField(strip=False)


class PasswordLoginForm(Form):
    email = types.EmailField(max_length=150)
    password = types.TextField(strip=False)


class PasswordSignupForm(ModelForm):
    model = User

    email: Field[str] = model_field()
    password: Field[str] = model_field()
    confirm_password = types.TextField(strip=False)

    def check(self) -> list[Error] | None:
        if self.password != self.confirm_password:
            return [
                Error(
                    "The two password fields didn't match.",
                    code="password_mismatch",
                    field="confirm_password",
                )
            ]
        return None
