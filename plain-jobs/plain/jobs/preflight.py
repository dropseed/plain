from __future__ import annotations

from plain.preflight import PreflightCheck, PreflightResult, register_check
from plain.runtime import settings
from plain.utils import timezone

from .exceptions import JobClassNotRegistered
from .scheduling import (
    load_schedule_entry,
    schedule_entry_display,
    schedule_entry_key,
    scheduled_concurrency_key,
)


@register_check(name="jobs.schedule")
class CheckJobsSchedule(PreflightCheck):
    """
    JOBS_SCHEDULE must load and every entry must be runnable: registered job
    classes, valid schedules that can actually match, distinct identities,
    and concurrency keys short enough to enqueue. The worker refuses to boot
    (or an entry silently never fires) otherwise, so catching it here stops
    the bad config at deploy time. Entries are checked individually so one
    broken entry doesn't hide the others.
    """

    def run(self) -> list[PreflightResult]:
        results = []
        loaded = []

        for entry in settings.JOBS_SCHEDULE:
            try:
                loaded.append(load_schedule_entry(entry))
            except JobClassNotRegistered as e:
                results.append(
                    PreflightResult(
                        fix=f"{e} Remove the JOBS_SCHEDULE entry or restore the class.",
                        id="jobs.schedule.unregistered_class",
                    )
                )
            except Exception as e:
                # Wrong entry shape, malformed cron string, out-of-range
                # field — the message says which.
                results.append(
                    PreflightResult(
                        fix=f"JOBS_SCHEDULE entry {entry!r} is invalid: {e}",
                        id="jobs.schedule.invalid",
                    )
                )

        seen_keys: set[str] = set()

        for job, schedule in loaded:
            key = schedule_entry_key(job, schedule)
            if key in seen_keys:
                results.append(
                    PreflightResult(
                        fix=(
                            f"Duplicate JOBS_SCHEDULE entry: {key!r}. Entries "
                            "with the same job class and schedule need distinct "
                            "default_concurrency_key() values."
                        ),
                        id="jobs.schedule.duplicate_entry",
                    )
                )
            seen_keys.add(key)

            try:
                schedule.next()
            except ValueError:
                # A warning, not an error: next() scans 500 days, so a valid
                # sparse schedule (e.g. Feb 29) can land here depending on
                # the date preflight runs — that must not block a deploy.
                results.append(
                    PreflightResult(
                        fix=(
                            f"JOBS_SCHEDULE entry {schedule_entry_display(job)!r} "
                            "does not match any time in the next 500 days — "
                            "check the schedule."
                        ),
                        id="jobs.schedule.never_matches",
                        warning=True,
                    )
                )

            if len(scheduled_concurrency_key(job, timezone.now())) > 255:
                results.append(
                    PreflightResult(
                        fix=(
                            f"JOBS_SCHEDULE entry {schedule_entry_display(job)!r} "
                            "has a default_concurrency_key() too long to enqueue "
                            "(concurrency_key is limited to 255 characters)."
                        ),
                        id="jobs.schedule.concurrency_key_too_long",
                    )
                )

        return results
