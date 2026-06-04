from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from app.users.models import User

from plain.email import TemplateEmail
from plain.exceptions import ValidationError
from plain.forms import Error

from .hashers import check_password, hash_password
from .utils import unicode_ci_compare


def check_user_password(user: Any, password: str) -> bool:
    # Run the default password hasher once to reduce the timing
    # difference between an existing and a nonexistent user (#20760).
    hash_password(password)

    # Update the stored hashed password if the hashing algorithm changed
    def setter(raw_password: str) -> None:
        user.password = raw_password
        user.update(fields=["password"])

    password_is_correct = check_password(password, user.password, setter)

    return password_is_correct


def get_password_errors(
    user: Any, password: str, *, field: str | None = None
) -> list[Error]:
    """Validate a new password against the password field's validators.

    Some validators compare the password against the user's other
    attributes, so the user is required. Returns the validators' own
    `Error`s — each carrying its `code` so callers can branch on which
    rule failed — or an empty list when the password is acceptable. The
    caller passes `field` to attach the errors to a form field.
    """
    try:
        # Clean it as if it were being assigned to the model field directly.
        user._model_meta.get_field("password").clean(password, user)
    except ValidationError as e:
        errors: list[Error] = []
        for leaf in e.error_list:
            message = leaf.message
            if leaf.params:
                message %= leaf.params
            errors.append(
                Error(message=str(message), code=leaf.code or "invalid", field=field)
            )
        return errors
    return []


def authenticate(*, email: str, password: str) -> User | None:
    """Return the user for these credentials, or None if they don't match.

    Runs the hasher once even when no user matches, so the timing of a
    missing user stays close to a wrong password (django #20760).
    """
    try:
        # Most users won't have a case-sensitive email, so we act that way.
        user = User.query.get(email__iexact=email)
    except User.DoesNotExist:
        check_password(password, "")
        return None

    if not check_user_password(user, password):
        return None

    return user


def set_user_password(user: User, password: str) -> User:
    """Set the user's password and save."""
    user.password = password
    user.update()
    return user


def _reset_users(email: str) -> Generator[User]:
    """Active users with this email who should receive a reset link."""
    users = User.query.filter(email__iexact=email)
    return (u for u in users if unicode_ci_compare(email, u.email))


def send_password_reset(
    *,
    email: str,
    generate_reset_url: Callable[[User], str],
    email_template_name: str = "password_reset",
    from_email: str = "",
    extra_email_context: dict[str, Any] | None = None,
) -> None:
    """Email a one-time reset link to each active user with this address."""
    for user in _reset_users(email):
        TemplateEmail(
            template=email_template_name,
            context={
                "email": email,
                "user": user,
                "url": generate_reset_url(user),
                **(extra_email_context or {}),
            },
            from_email=from_email,
            to=[user.email],
            headers={"X-Auto-Response-Suppress": "All"},
        ).send()
