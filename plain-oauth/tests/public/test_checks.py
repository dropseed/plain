from app.users.models import User

from plain.oauth.models import OAuthConnection
from plain.oauth.preflight import CheckOAuthProviderKeys
from plain.test import override_settings


def test_oauth_provider_keys_check_pass():
    with override_settings(
        OAUTH_LOGIN_PROVIDERS={
            "google": {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
            },
            "foo": {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
            },
        }
    ):
        user = User.query.create(username="test_user", email="test@example.com")

        OAuthConnection.query.create(
            user=user,
            provider_key="google",
            provider_user_id="test_provider_user_id",
            access_token="test",
        )

        check = CheckOAuthProviderKeys()
        errors = check.run()
        assert len(errors) == 0


def test_oauth_provider_keys_check_fail():
    with override_settings(
        OAUTH_LOGIN_PROVIDERS={
            "google": {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
            },
            "foo": {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
            },
        }
    ):
        user = User.query.create(username="test_user", email="test@example.com")

        OAuthConnection.query.create(
            user=user,
            provider_key="google",
            provider_user_id="test_provider_user_id",
            access_token="test",
        )
        OAuthConnection.query.create(
            user=user,
            provider_key="bar",
            provider_user_id="test_provider_user_id",
            access_token="test",
        )

        check = CheckOAuthProviderKeys()
        errors = check.run()
        assert len(errors) == 1
        assert (
            errors[0].fix
            == "The following OAuth providers are in the database but not in the settings: bar. Add these providers to your OAUTH_LOGIN_PROVIDERS setting or remove the corresponding OAuthConnection records."
        )
