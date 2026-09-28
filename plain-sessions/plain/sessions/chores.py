from plain.chores import Chore, register_chore
from plain.utils import timezone

from .models import Session


@register_chore
class ClearExpired(Chore):
    """Delete sessions that have expired."""

    def run(self) -> str:
        count = Session.query.where(Session.expires_at.lt(timezone.now())).delete()
        return f"{count} expired sessions deleted"
