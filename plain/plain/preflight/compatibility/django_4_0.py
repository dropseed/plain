from plain.runtime import settings

from .. import Error, register


@register
def check_csrf_trusted_origins(package_configs, **kwargs):
    errors = []
    for origin in settings.CSRF_TRUSTED_ORIGINS:
        if "://" not in origin:
            errors.append(
                Error(
                    "As of Plain 4.0, the values in the CSRF_TRUSTED_ORIGINS "
                    "setting must start with a scheme (usually http:// or "
                    "https://) but found %s. See the release notes for details."
                    % origin,
                    id="4_0.E001",
                )
            )
    return errors
