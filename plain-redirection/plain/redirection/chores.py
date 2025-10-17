from __future__ import annotations

from plain.chores import Chore, register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import NotFoundLog, RedirectLog


@register_chore
class DeleteLogs(Chore):
    """Delete logs older than REDIRECTION_LOG_RETENTION_TIMEDELTA."""

    def run(self) -> str:
        cutoff = timezone.now() - settings.REDIRECTION_LOG_RETENTION_TIMEDELTA

        result = RedirectLog.query.filter(created_at__lt=cutoff).delete()
        output = f"{result[0]} redirect logs deleted"

        result = NotFoundLog.query.filter(created_at__lt=cutoff).delete()
        output += f", {result[0]} not found logs deleted"

        return output
