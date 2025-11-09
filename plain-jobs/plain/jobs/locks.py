"""Lock implementations for job enqueueing."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .jobs import Job


@contextmanager
def postgres_advisory_lock(job: Job, concurrency_key: str) -> Iterator[None]:
    """
    PostgreSQL advisory lock context manager.

    Generates lock key from job class + concurrency_key, acquires advisory lock.
    Uses pg_advisory_xact_lock which is automatically released when the
    transaction commits or rolls back. No explicit release needed.

    Args:
        job: Job instance (used to get job class name)
        concurrency_key: Job grouping key
    """
    from plain.jobs.registry import jobs_registry
    from plain.models.db import db_connection

    # Generate lock key from job class + concurrency_key
    job_class_name = jobs_registry.get_job_class_name(job.__class__)
    lock_key = f"{job_class_name}::{concurrency_key}"

    # Convert lock key to int64 for PostgreSQL advisory lock
    hash_bytes = hashlib.md5(lock_key.encode()).digest()
    lock_id = int.from_bytes(hash_bytes[:8], "big", signed=True)

    # Acquire advisory lock (auto-released on transaction end)
    with db_connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [lock_id])

    yield  # Lock is held here
