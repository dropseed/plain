from __future__ import annotations

from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult

_SECRET_KEY_MIN_LENGTH = 50
_SECRET_KEY_MIN_UNIQUE_CHARACTERS = 5


def _check_secret_key(secret_key: str) -> bool:
    return (
        len(set(secret_key)) >= _SECRET_KEY_MIN_UNIQUE_CHARACTERS
        and len(secret_key) >= _SECRET_KEY_MIN_LENGTH
    )


@register_check(name="security.secret_key", deploy=True)
class CheckSecretKey(PreflightCheck):
    """Validates that SECRET_KEY is long and random enough for security."""

    def run(self) -> list[PreflightResult]:
        if not _check_secret_key(settings.SECRET_KEY):
            return [
                PreflightResult(
                    fix=f"SECRET_KEY is too weak (needs {_SECRET_KEY_MIN_LENGTH}+ characters, "
                    f"{_SECRET_KEY_MIN_UNIQUE_CHARACTERS}+ unique). Generate a new long random value or "
                    f"Plain's security features will be vulnerable to attack.",
                    id="security.secret_key_weak",
                )
            ]
        return []


@register_check(name="security.secret_key_fallbacks", deploy=True)
class CheckSecretKeyFallbacks(PreflightCheck):
    """Validates that SECRET_KEY_FALLBACKS are long and random enough for security."""

    def run(self) -> list[PreflightResult]:
        errors = []
        for index, key in enumerate(settings.SECRET_KEY_FALLBACKS):
            if not _check_secret_key(key):
                errors.append(
                    PreflightResult(
                        fix=f"SECRET_KEY_FALLBACKS[{index}] is too weak (needs {_SECRET_KEY_MIN_LENGTH}+ characters, "
                        f"{_SECRET_KEY_MIN_UNIQUE_CHARACTERS}+ unique). Generate a new long random value or "
                        f"Plain's security features will be vulnerable to attack.",
                        id="security.secret_key_fallback_weak",
                    )
                )
        return errors


@register_check(name="security.debug", deploy=True)
class CheckDebug(PreflightCheck):
    """Ensures DEBUG is False in production deployment."""

    def run(self) -> list[PreflightResult]:
        if settings.DEBUG:
            return [
                PreflightResult(
                    fix="DEBUG is True in deployment. Set DEBUG=False to prevent exposing sensitive information.",
                    id="security.debug_enabled_in_production",
                )
            ]
        return []


@register_check(name="security.allowed_hosts", deploy=True)
class CheckAllowedHosts(PreflightCheck):
    """Ensures ALLOWED_HOSTS is not empty in production deployment."""

    def run(self) -> list[PreflightResult]:
        if not settings.ALLOWED_HOSTS:
            return [
                PreflightResult(
                    fix="ALLOWED_HOSTS is empty in deployment. Add your domain(s) to prevent host header attacks.",
                    id="security.allowed_hosts_empty",
                )
            ]
        return []
