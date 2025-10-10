from plain.auth import get_user_model
from plain.oauth.models import OAuthConnection
from plain.oauth.preflight import CheckOAuthProviderKeys


def test_oauth_provider_keys_check_pass(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "google": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        },
        "foo": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        },
    }

    user = get_user_model().query.create(username="test_user", email="test@example.com")

    OAuthConnection.query.create(
        user=user,
        provider_key="google",
        provider_user_id="test_provider_user_id",
        access_token="test",
    )

    check = CheckOAuthProviderKeys()
    errors = check.run()
    assert len(errors) == 0


def test_oauth_provider_keys_check_fail(db, settings):
    settings.OAUTH_LOGIN_PROVIDERS = {
        "google": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        },
        "foo": {
            "client_id": "test_client_id",
            "client_secret": "test_client_secret",
        },
    }

    user = get_user_model().query.create(username="test_user", email="test@example.com")

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
