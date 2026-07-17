"""The ClearExpiredOAuthTokens cleanup chore."""

from __future__ import annotations

from datetime import timedelta

from oauth_helpers import issue_token_pair, make_public_app, make_user

from plain.oauthserver.chores import ClearExpiredOAuthTokens
from plain.oauthserver.models import (
    AccessToken,
    AuthorizationCode,
    RefreshToken,
)
from plain.utils import timezone


def _code(application, user, *, used=False, expired=False):
    now = timezone.now()
    return AuthorizationCode.query.create(
        application=application,
        user=user,
        redirect_uri="http://localhost/cb",
        code_challenge="x",
        used=used,
        expires_at=now - timedelta(minutes=1)
        if expired
        else now + timedelta(minutes=10),
    )


class TestClearExpiredOAuthTokens:
    def test_spent_and_expired_codes_deleted_live_kept(self):
        user = make_user()
        public_app = make_public_app()
        live = _code(public_app, user)
        _code(public_app, user, used=True)
        _code(public_app, user, expired=True)

        ClearExpiredOAuthTokens().run()

        assert list(AuthorizationCode.query.all()) == [live]

    def test_revoked_pair_deleted(self):
        user = make_user()
        public_app = make_public_app()
        access, refresh = issue_token_pair(public_app, user)
        refresh.revoked = True
        refresh.update(fields=["revoked"])
        access.revoked = True
        access.update(fields=["revoked"])

        ClearExpiredOAuthTokens().run()

        assert not AccessToken.query.filter(id=access.id).exists()
        assert not RefreshToken.query.filter(id=refresh.id).exists()

    def test_valid_refresh_keeps_its_expired_access_token(self):
        # The cascade-safety guarantee: an access token expires after an hour
        # while its refresh token lives for weeks. Pruning the expired access
        # token would CASCADE-delete the still-valid refresh — so it must stay.
        user = make_user()
        public_app = make_public_app()
        access, refresh = issue_token_pair(public_app, user)
        access.expires_at = timezone.now() - timedelta(minutes=1)
        access.update(fields=["expires_at"])

        ClearExpiredOAuthTokens().run()

        assert AccessToken.query.filter(id=access.id).exists()
        assert RefreshToken.query.filter(id=refresh.id).exists()
