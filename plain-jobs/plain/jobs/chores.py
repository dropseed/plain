import datetime

from plain.chores import Chore, register_chore
from plain.runtime import settings
from plain.utils import timezone

from .models import JobResult, ScheduleState
from .scheduling import load_schedule, schedule_entry_key


@register_chore
class ClearCompleted(Chore):
    """Delete all completed job results in all queues."""

    def run(self) -> str:
        cutoff = timezone.now() - datetime.timedelta(
            seconds=settings.JOBS_RESULTS_RETENTION
        )
        count = JobResult.query.filter(created_at__lt=cutoff).delete()
        return f"{count} jobs deleted"


@register_chore
class PruneScheduleLedger(Chore):
    """Delete ScheduleState rows for entries no longer in JOBS_SCHEDULE.

    Queue-scoped workers only see their own entries, so they can't tell a
    removed entry from another queue's — but chores run with the full
    schedule config, making the deletion safe here. A row deleted out from
    under a worker on a different config just re-initializes on its next
    pass.
    """

    def run(self) -> str:
        current_keys = [
            schedule_entry_key(job, schedule)
            for job, schedule in load_schedule(settings.JOBS_SCHEDULE)
        ]
        count = ScheduleState.query.exclude(schedule_key__in=current_keys).delete()
        return f"{count} stale schedule ledger rows deleted"
