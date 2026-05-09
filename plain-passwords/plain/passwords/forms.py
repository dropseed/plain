from __future__ import annotations

from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from plain.exceptions import ValidationError
from plain.schema import Schema, types

from .core import check_user_password
from .hashers import check_password
from .utils import unicode_ci_compare

if TYPE_CHECKING:
    from app.users.models import User


class PasswordResetSchema(Schema):
    email: str = types.EmailField(max_length=254)

    def send_mail(
        self,
        *,
        template_name: str,
        context: dict[str, Any],
        from_email: str,
        to_email: str,
    ) -> None:
        from plain.email import TemplateEmail

        email = TemplateEmail(
            template=template_name,
            context=context,
            from_email=from_email,
            to=[to_email],
            headers={"X-Auto-Response-Suppress": "All"},
        )
        email.send()

    def get_users(self, email: str) -> Generator[User]:
        """Given an email, return matching user(s) who should receive a reset.

        Override to customize the default policies that prevent inactive
        users and users with unusable passwords from resetting their
        password.
        """
        from app.users.models import User

        active_users = User.query.filter(email__iexact=email)
        return (u for u in active_users if unicode_ci_compare(email, u.email))

    def save(
        self,
        *,
        generate_reset_url: Callable[[User], str],
        email_template_name: str = "password_reset",
        from_email: str = "",
        extra_email_context: dict[str, Any] | None = None,
    ) -> None:
        """Generate a one-use only link for resetting password and send it
        to the user."""
        for user in self.get_users(self.email):
            context = {
                "email": self.email,
                "user": user,
                "url": generate_reset_url(user),
                **(extra_email_context or {}),
            }
            self.send_mail(
                template_name=email_template_name,
                context=context,
                from_email=from_email,
                to_email=user.email,
            )


class PasswordSetSchema(Schema):
    """Set a new password without entering the old one. The view passes the
    target `User` via `validate(..., context={"user": user})` and then again
    on `save(user=...)`."""

    new_password1: str = types.TextField(strip=False)
    new_password2: str = types.TextField(strip=False)

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        if self.new_password1 != self.new_password2:
            return {
                "new_password2": ["The two password fields didn't match."],
            }

        # Run the model field validators on the new password — context["user"]
        # gives us the target row whose password slot we're filling.
        user: User | None = (context or {}).get("user")
        if user is not None:
            field = user._model_meta.get_field("password")
            try:
                field.clean(self.new_password2, user)  # ty: ignore[unresolved-attribute]
            except ValidationError as e:
                return {"new_password2": list(e.messages)}
        return None

    def save(self, *, user: User) -> User:
        user.password = self.new_password1
        user.save()
        return user


class PasswordChangeSchema(PasswordSetSchema):
    """Change an existing password by also entering the current one."""

    current_password: str = types.TextField(strip=False)

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        user: User | None = (context or {}).get("user")
        if user is not None and not check_user_password(user, self.current_password):
            return {
                "current_password": [
                    "Your old password was entered incorrectly. Please enter it again."
                ],
            }
        return super().check(context=context)


class PasswordLoginSchema(Schema):
    """Validates email/password format. Authentication itself happens in the
    view (`PasswordLoginView.schema_valid`) so the schema stays a pure
    parser — no `_user` instance state."""

    email: str = types.EmailField(max_length=150)
    password: str = types.TextField(strip=False)


def authenticate(email: str, password: str) -> User | None:
    """Look up a user by email and verify their password.

    Returns the User on success, None on failure. Always runs a hash check
    even when the user doesn't exist, to reduce the timing difference
    between an existing and a nonexistent user.
    """
    from app.users.models import User

    try:
        user = User.query.get(email__iexact=email)
    except User.DoesNotExist:
        check_password(password, "")
        return None

    if not check_user_password(user, password):
        return None
    return user


class PasswordSignupSchema(Schema):
    """Sign up a new user. Schema declares the user-facing fields directly
    (the previous ModelForm version auto-derived them from User)."""

    email: str = types.EmailField()
    password: str = types.TextField(strip=False)
    confirm_password: str = types.TextField(strip=False)

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        if self.password != self.confirm_password:
            return {"confirm_password": ["The two password fields didn't match."]}
        return None

    def save(self) -> User:
        from app.users.models import User

        return User.query.create(email=self.email, password=self.password)
