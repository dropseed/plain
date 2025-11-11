from plain.models.db import OperationalError, ProgrammingError
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check(name="oauth.provider_keys")
class CheckOAuthProviderKeys(PreflightCheck):
    """
    Check for OAuth provider keys in the database that are not present in settings.
    """

    def run(self) -> list[PreflightResult]:
        from .models import OAuthConnection
        from .providers import get_provider_keys

        errors = []

        try:
            keys_in_db = set(
                OAuthConnection.query.values_list("provider_key", flat=True).distinct()
            )
        except (OperationalError, ProgrammingError):
            # Check runs on plain migrate, and the table may not exist yet
            # or it may not be installed on the particular database intentionally
            return errors

        keys_in_settings = set(get_provider_keys())

        if keys_in_db - keys_in_settings:
            errors.append(
                PreflightResult(
                    fix="The following OAuth providers are in the database but not in the settings: {}. Add these providers to your OAUTH_LOGIN_PROVIDERS setting or remove the corresponding OAuthConnection records.".format(
                        ", ".join(keys_in_db - keys_in_settings)
                    ),
                    id="oauth.provider_settings_missing",
                )
            )

        return errors
