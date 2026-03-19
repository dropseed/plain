from __future__ import annotations

import datetime

from plain.jobs.models import JobRequest
from plain.utils import timezone


def test_higher_priority_jobs_ordered_first(db):
    """Higher priority number = higher priority = should come first in queries."""
    now = timezone.now()

    low = JobRequest.query.create(
        job_class="app.LowPriorityJob",
        priority=1,
        created_at=now,
    )
    high = JobRequest.query.create(
        job_class="app.HighPriorityJob",
        priority=10,
        created_at=now,
    )
    medium = JobRequest.query.create(
        job_class="app.MediumPriorityJob",
        priority=5,
        created_at=now,
    )

    jobs = list(JobRequest.query.all())
    assert jobs[0].id == high.id
    assert jobs[1].id == medium.id
    assert jobs[2].id == low.id


def test_same_priority_ordered_by_created_at_descending(db):
    """Jobs with the same priority should be ordered newest first (default ordering)."""
    now = timezone.now()

    first = JobRequest.query.create(
        job_class="app.JobA",
        priority=5,
        created_at=now - datetime.timedelta(minutes=2),
    )
    second = JobRequest.query.create(
        job_class="app.JobB",
        priority=5,
        created_at=now - datetime.timedelta(minutes=1),
    )
    third = JobRequest.query.create(
        job_class="app.JobC",
        priority=5,
        created_at=now,
    )

    jobs = list(JobRequest.query.all())
    assert jobs[0].id == third.id
    assert jobs[1].id == second.id
    assert jobs[2].id == first.id


def test_worker_ordering_priority_then_created_at(db):
    """The worker query orders by -priority, -start_at, -created_at."""
    now = timezone.now()

    low_old = JobRequest.query.create(
        job_class="app.Job1",
        priority=1,
        queue="default",
        created_at=now - datetime.timedelta(minutes=5),
    )
    low_new = JobRequest.query.create(
        job_class="app.Job2",
        priority=1,
        queue="default",
        created_at=now,
    )
    high_old = JobRequest.query.create(
        job_class="app.Job3",
        priority=10,
        queue="default",
        created_at=now - datetime.timedelta(minutes=5),
    )

    # Simulate the worker's query (without select_for_update for test simplicity)
    from plain import postgres

    jobs = list(
        JobRequest.query.filter(queue__in=["default"])
        .filter(postgres.Q(start_at__isnull=True) | postgres.Q(start_at__lte=now))
        .order_by("-priority", "-start_at", "-created_at")
    )

    # High priority job should be first regardless of created_at
    assert jobs[0].id == high_old.id
    # Then same-priority jobs ordered by created_at descending (newer first)
    assert jobs[1].id == low_new.id
    assert jobs[2].id == low_old.id
