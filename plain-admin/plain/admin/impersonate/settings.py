from typing import Any

from plain.runtime import settings


def IMPERSONATE_ALLOWED(user: Any) -> bool:
    if hasattr(settings, "IMPERSONATE_ALLOWED"):
        return settings.IMPERSONATE_ALLOWED(user)

    return user.is_admin
