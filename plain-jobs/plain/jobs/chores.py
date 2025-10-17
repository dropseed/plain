import datetime

from plain.chores import Chore, register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import JobResult


@register_chore
class ClearCompleted(Chore):
    """Delete all completed job results in all queues."""

    def run(self) -> str:
        cutoff = timezone.now() - datetime.timedelta(
            seconds=settings.JOBS_RESULTS_RETENTION
        )
        results = JobResult.query.filter(created_at__lt=cutoff).delete()
        return f"{results[0]} jobs deleted"
