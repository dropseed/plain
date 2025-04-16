from plain.chores import register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import NotFoundLog, RedirectLog


@register_chore("redirection")
def delete_logs():
    """
    Delete logs older than REDIRECTION_LOG_RETENTION_TIMEDELTA.
    """
    cutoff = timezone.now() - settings.REDIRECTION_LOG_RETENTION_TIMEDELTA

    result = RedirectLog.objects.filter(created_at__lt=cutoff).delete()
    output = f"{result[0]} redirect logs deleted"

    result = NotFoundLog.objects.filter(created_at__lt=cutoff).delete()
    output += f", {result[0]} not found logs deleted"

    return output
