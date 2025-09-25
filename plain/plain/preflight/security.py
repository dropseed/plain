from plain.runtime import settings

from .checks import PreflightCheck
from .registry import register_check
from .results import PreflightResult

SECRET_KEY_MIN_LENGTH = 50
SECRET_KEY_MIN_UNIQUE_CHARACTERS = 5


def _check_secret_key(secret_key):
    return (
        len(set(secret_key)) >= SECRET_KEY_MIN_UNIQUE_CHARACTERS
        and len(secret_key) >= SECRET_KEY_MIN_LENGTH
    )


@register_check(name="security.secret_key", deploy=True)
class CheckSecretKey(PreflightCheck):
    """Validates that SECRET_KEY is long and random enough for security."""

    def run(self):
        if not _check_secret_key(settings.SECRET_KEY):
            return [
                PreflightResult(
                    f"Your SECRET_KEY has less than {SECRET_KEY_MIN_LENGTH} characters or less than "
                    f"{SECRET_KEY_MIN_UNIQUE_CHARACTERS} unique characters. Please generate "
                    f"a long and random value, otherwise many of Plain's security-critical "
                    f"features will be vulnerable to attack.",
                    id="security.secret_key_weak",
                )
            ]
        return []


@register_check(name="security.secret_key_fallbacks", deploy=True)
class CheckSecretKeyFallbacks(PreflightCheck):
    """Validates that SECRET_KEY_FALLBACKS are long and random enough for security."""

    def run(self):
        errors = []
        for index, key in enumerate(settings.SECRET_KEY_FALLBACKS):
            if not _check_secret_key(key):
                errors.append(
                    PreflightResult(
                        f"Your SECRET_KEY_FALLBACKS[{index}] has less than {SECRET_KEY_MIN_LENGTH} characters or less than "
                        f"{SECRET_KEY_MIN_UNIQUE_CHARACTERS} unique characters. Please generate "
                        f"a long and random value, otherwise many of Plain's security-critical "
                        f"features will be vulnerable to attack.",
                        id="security.secret_key_fallback_weak",
                    )
                )
        return errors


@register_check(name="security.debug", deploy=True)
class CheckDebug(PreflightCheck):
    """Ensures DEBUG is False in production deployment."""

    def run(self):
        if settings.DEBUG:
            return [
                PreflightResult(
                    "You should not have DEBUG set to True in deployment.",
                    id="security.debug_enabled_in_production",
                )
            ]
        return []


@register_check(name="security.allowed_hosts", deploy=True)
class CheckAllowedHosts(PreflightCheck):
    """Ensures ALLOWED_HOSTS is not empty in production deployment."""

    def run(self):
        if not settings.ALLOWED_HOSTS:
            return [
                PreflightResult(
                    "ALLOWED_HOSTS must not be empty in deployment.",
                    id="security.allowed_hosts_empty",
                )
            ]
        return []
