from plain.chores import Chore, register_chore
from plain.utils import timezone

from .models import Session


@register_chore
class ClearExpired(Chore):
    """Delete sessions that have expired."""

    def run(self) -> str:
        result = Session.query.filter(expires_at__lt=timezone.now()).delete()
        return f"{result[0]} expired sessions deleted"
