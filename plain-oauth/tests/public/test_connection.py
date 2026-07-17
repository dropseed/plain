"""Contract tests for OAuthConnection account linking and token expiry.

These exercise the model logic directly (no HTTP round-trip): first-time
sign-up, returning users, the account-takeover guard when an email is
already registered, connect() idempotency, and token-expiry helpers.
"""

from __future__ import annotations

from datetime import timedelta

from app.users.models import User

from plain.oauth.exceptions import OAuthUserAlreadyExistsError
from plain.oauth.models import OAuthConnection
from plain.oauth.providers import OAuthToken, OAuthUser
from plain.test import raises
from plain.utils import timezone

PROVIDER = "dummy"


def make_oauth_user(provider_id="prov-1", email="new@example.com", username="new"):
    return OAuthUser(
        provider_id=provider_id,
        user_model_fields={"email": email, "username": username},
    )


def test_first_login_creates_user_and_connection():
    connection = OAuthConnection.get_or_create_user(
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="tok-1"),
        oauth_user=make_oauth_user(),
    )

    assert User.query.filter(email="new@example.com").count() == 1
    assert connection.provider_key == PROVIDER
    assert connection.provider_user_id == "prov-1"
    assert connection.access_token == "tok-1"
    assert connection.user.email == "new@example.com"


def test_returning_user_reuses_connection_and_updates_token():
    first = OAuthConnection.get_or_create_user(
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="tok-1"),
        oauth_user=make_oauth_user(),
    )

    second = OAuthConnection.get_or_create_user(
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="tok-2"),
        oauth_user=make_oauth_user(),
    )

    # Same connection and user — no duplicate account created.
    assert second.id == first.id
    assert User.query.count() == 1
    assert OAuthConnection.query.count() == 1
    # Token refreshed on return.
    assert second.access_token == "tok-2"


def test_existing_email_without_connection_is_rejected():
    # A user already registered this email (e.g. via password signup) but has
    # no OAuth connection. Auto-linking would be an account-takeover vector.
    User.query.create(email="taken@example.com", username="existing")

    with raises(OAuthUserAlreadyExistsError):
        OAuthConnection.get_or_create_user(
            provider_key=PROVIDER,
            oauth_token=OAuthToken(access_token="tok"),
            oauth_user=make_oauth_user(
                provider_id="prov-2", email="taken@example.com", username="newname"
            ),
        )

    # No connection was created for the pre-existing account.
    assert OAuthConnection.query.count() == 0


def test_connect_is_idempotent_for_same_user_and_provider():
    user = User.query.create(email="u@example.com", username="u")

    first = OAuthConnection.connect(
        user=user,
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="a"),
        oauth_user=make_oauth_user(provider_id="pid", email="u@example.com"),
    )
    second = OAuthConnection.connect(
        user=user,
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="b"),
        oauth_user=make_oauth_user(provider_id="pid", email="u@example.com"),
    )

    assert second.id == first.id
    assert OAuthConnection.query.filter(user=user).count() == 1
    assert second.access_token == "b"


def test_access_token_expired():
    user = User.query.create(email="e@example.com", username="e")
    conn = OAuthConnection.connect(
        user=user,
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="a"),
        oauth_user=make_oauth_user(provider_id="pid", email="e@example.com"),
    )

    # No expiry set -> never considered expired.
    assert conn.access_token_expired() is False

    conn.access_token_expires_at = timezone.now() - timedelta(minutes=1)
    assert conn.access_token_expired() is True

    conn.access_token_expires_at = timezone.now() + timedelta(minutes=1)
    assert conn.access_token_expired() is False


def test_refresh_token_expired():
    user = User.query.create(email="r@example.com", username="r")
    conn = OAuthConnection.connect(
        user=user,
        provider_key=PROVIDER,
        oauth_token=OAuthToken(access_token="a"),
        oauth_user=make_oauth_user(provider_id="pid", email="r@example.com"),
    )

    assert conn.refresh_token_expired() is False

    conn.refresh_token_expires_at = timezone.now() - timedelta(minutes=1)
    assert conn.refresh_token_expired() is True
