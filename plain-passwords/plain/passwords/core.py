from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from app.users.models import User
from plain.email import TemplateEmail

from .hashers import check_password, hash_password
from .utils import unicode_ci_compare
from .values import HashedPassword


def check_user_password(user: Any, raw_password: str) -> bool:
    """Whether this raw password is the user's, rehashing it if it's stale."""
    # Run the default password hasher once to reduce the timing difference
    # between an existing and a nonexistent user (django #20760).
    hash_password(raw_password)

    if not user.password.check(raw_password):
        return False

    # Rehashing needs the raw password, and this is the only moment it's in
    # hand — so an upgraded hasher takes effect on the user's next login.
    if user.password.needs_rehash():
        user.password = HashedPassword.from_raw(raw_password)
        user.update(fields=["password"])

    return True


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


def set_user_password(user: User, password: HashedPassword) -> User:
    """Store an already-hashed password on the user and save.

    Takes a `HashedPassword`, not a raw string — hashing and raw-password
    validation both happen in the form layer.
    """
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
