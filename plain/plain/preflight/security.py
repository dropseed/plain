from plain.exceptions import ImproperlyConfigured
from plain.runtime import settings

from .messages import Warning
from .registry import register_check

SECRET_KEY_MIN_LENGTH = 50
SECRET_KEY_MIN_UNIQUE_CHARACTERS = 5

SECRET_KEY_WARNING_MSG = (
    f"Your %s has less than {SECRET_KEY_MIN_LENGTH} characters or less than "
    f"{SECRET_KEY_MIN_UNIQUE_CHARACTERS} unique characters. Please generate "
    f"a long and random value, otherwise many of Plain's security-critical "
    f"features will be vulnerable to attack."
)

W025 = Warning(SECRET_KEY_WARNING_MSG, id="security.W025")


def _check_secret_key(secret_key):
    return (
        len(set(secret_key)) >= SECRET_KEY_MIN_UNIQUE_CHARACTERS
        and len(secret_key) >= SECRET_KEY_MIN_LENGTH
    )


@register_check(deploy=True)
def check_secret_key(package_configs, **kwargs):
    try:
        secret_key = settings.SECRET_KEY
    except (ImproperlyConfigured, AttributeError):
        passed_check = False
    else:
        passed_check = _check_secret_key(secret_key)
    return (
        []
        if passed_check
        else [
            Warning(
                SECRET_KEY_WARNING_MSG % "SECRET_KEY",
                id="security.W009",
            )
        ]
    )


@register_check(deploy=True)
def check_secret_key_fallbacks(package_configs, **kwargs):
    warnings = []
    try:
        fallbacks = settings.SECRET_KEY_FALLBACKS
    except (ImproperlyConfigured, AttributeError):
        warnings.append(Warning(W025.msg % "SECRET_KEY_FALLBACKS", id=W025.id))
    else:
        for index, key in enumerate(fallbacks):
            if not _check_secret_key(key):
                warnings.append(
                    Warning(W025.msg % f"SECRET_KEY_FALLBACKS[{index}]", id=W025.id)
                )
    return warnings


@register_check(deploy=True)
def check_debug(package_configs, **kwargs):
    passed_check = not settings.DEBUG
    return (
        []
        if passed_check
        else [
            Warning(
                "You should not have DEBUG set to True in deployment.",
                id="security.W018",
            )
        ]
    )


@register_check(deploy=True)
def check_allowed_hosts(package_configs, **kwargs):
    return (
        []
        if settings.ALLOWED_HOSTS
        else [
            Warning(
                "ALLOWED_HOSTS must not be empty in deployment.",
                id="security.W020",
            )
        ]
    )
