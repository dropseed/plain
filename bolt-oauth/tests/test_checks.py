import pytest
from django.contrib.auth import get_user_model

from forgeoauth.models import OAuthConnection


@pytest.mark.django_db
def test_oauth_provider_keys_check_pass(settings):
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

    user = get_user_model().objects.create_user(username="test_user")

    OAuthConnection.objects.create(
        user=user, provider_key="google", provider_user_id="test_provider_user_id"
    )

    errors = OAuthConnection.check(databases=["default"])
    assert len(errors) == 0


@pytest.mark.django_db
def test_oauth_provider_keys_check_pass(settings):
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

    user = get_user_model().objects.create_user(username="test_user")

    OAuthConnection.objects.create(
        user=user, provider_key="google", provider_user_id="test_provider_user_id"
    )
    OAuthConnection.objects.create(
        user=user, provider_key="bar", provider_user_id="test_provider_user_id"
    )

    errors = OAuthConnection.check(databases=["default"])
    assert len(errors) == 1
    assert (
        errors[0].msg
        == "The following OAuth providers are in the database but not in the settings: bar"
    )
