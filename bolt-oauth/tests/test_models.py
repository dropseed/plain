import pytest

from forgeoauth.models import OAuthConnection
from forgeoauth.providers import OAuthToken, OAuthUser


@pytest.mark.django_db
def test_email_normalized():
    """Make sure that the normalize_email function is being called somewhere in here (was concerned it wasn't)"""
    connection = OAuthConnection.get_or_createuser(
        provider_key="dummy",
        oauth_token=OAuthToken(
            access_token="dummy_access_token",
        ),
        oauth_user=OAuthUser(
            id="dummy_id",
            username="dummy_username",
            email="Dummy@ExAmPlE.com",
        ),
    )
    assert connection.user.email == "Dummy@example.com"
