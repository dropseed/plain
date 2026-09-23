from plain.chores import Chore, register_chore
from plain.utils import timezone

from .models import AccessToken, AuthorizationCode, RefreshToken


@register_chore
class ClearExpiredOAuthTokens(Chore):
    """Delete spent authorization codes and dead OAuth tokens.

    Refresh-token rotation issues a new pair on every use, so without this
    these tables grow unbounded and the hot-path code/token lookups slow down.
    """

    def run(self) -> str:
        now = timezone.now()

        codes = AuthorizationCode.query.where(
            AuthorizationCode.used.equals(True) | AuthorizationCode.expires_at.lt(now)
        ).delete()

        # Refresh tokens first: a RefreshToken's CASCADE FK to AccessToken means
        # deleting an access token would take a still-valid refresh with it. So
        # drop dead refresh tokens up front, then only remove access tokens that
        # no surviving (valid) refresh token still points at.
        refresh = RefreshToken.query.where(
            RefreshToken.revoked.equals(True) | RefreshToken.expires_at.lt(now)
        ).delete()

        live_access_ids = RefreshToken.query.select(
            RefreshToken.access_token.id, flat=True
        )
        access = (
            AccessToken.query.where(
                AccessToken.revoked.equals(True) | AccessToken.expires_at.lt(now)
            )
            .where(~AccessToken.id.is_in(live_access_ids))
            .delete()
        )

        return (
            f"{codes} codes, {refresh} refresh tokens, {access} access tokens deleted"
        )
