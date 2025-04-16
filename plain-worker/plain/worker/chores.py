import datetime

from plain.chores import register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import JobResult


@register_chore("worker")
def clear_completed():
    """Delete all completed job results in all queues."""
    cutoff = timezone.now() - datetime.timedelta(
        seconds=settings.WORKER_JOBS_CLEARABLE_AFTER
    )
    results = JobResult.objects.filter(created_at__lt=cutoff).delete()
    return f"{results[0]} jobs deleted"
