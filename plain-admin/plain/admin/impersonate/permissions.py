from typing import Any

from . import settings


def can_be_impersonator(user: Any) -> bool:
    return settings.IMPERSONATE_ALLOWED(user)


def can_impersonate_user(impersonator: Any, target_user: Any) -> bool:
    if not can_be_impersonator(impersonator):
        return False

    # You can't impersonate admin users
    if target_user.is_admin:
        return False

    return True
