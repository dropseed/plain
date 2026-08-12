"""The jobs.schedule preflight check: every way JOBS_SCHEDULE can be broken
is reported at deploy time, per entry, without hiding the others."""

from __future__ import annotations

from plain.jobs import Job
from plain.jobs.preflight import CheckJobsSchedule
from plain.jobs.registry import jobs_registry, register_job


@register_job
class _PreflightJob(Job):
    def run(self) -> None:
        pass


@register_job
class _LongKeyJob(Job):
    def run(self) -> None:
        pass

    def default_concurrency_key(self) -> str:
        return "x" * 300


class _UnregisteredJob(Job):
    """Deliberately not @register_job'd."""

    def run(self) -> None:
        pass


JOB = jobs_registry.get_job_class_name(_PreflightJob)


def _check(settings, schedule) -> list[str]:
    settings.JOBS_SCHEDULE = schedule
    return [result.id for result in CheckJobsSchedule().run()]


def test_valid_schedule_passes(settings):
    assert _check(settings, [(JOB, "@daily"), ("cmd:echo ok", "@hourly")]) == []


def test_unregistered_class(settings):
    assert _check(settings, [("app.gone.RemovedJob", "@daily")]) == [
        "jobs.schedule.unregistered_class"
    ]


def test_malformed_cron_string(settings):
    assert _check(settings, [(JOB, "* * * *")]) == ["jobs.schedule.invalid"]


def test_out_of_range_cron_field_is_blocking(settings):
    # Range validation happens at parse time for string fields too — this
    # must be a blocking `invalid`, not the nonblocking never-matches
    # warning (or a worker that error-loops on every pass).
    assert _check(settings, [(JOB, "0 25 * * *")]) == ["jobs.schedule.invalid"]
    assert _check(settings, [(JOB, "0 20-30 * * *")]) == ["jobs.schedule.invalid"]


def test_malformed_entry_shape(settings):
    # A non-tuple entry is rejected by settings typing before preflight ever
    # sees it; a wrong-arity tuple gets through and is reported here.
    assert _check(settings, [(JOB,)]) == ["jobs.schedule.invalid"]


def test_wrong_member_types(settings):
    # Members of the tuple aren't settings-validated — a None schedule or a
    # non-Job object must be reported, not crash the check.
    assert _check(settings, [(_PreflightJob(), None)]) == ["jobs.schedule.invalid"]
    assert _check(settings, [(object(), "@daily")]) == ["jobs.schedule.invalid"]


def test_unregistered_job_instance(settings):
    # An instance loads fine but its rows could never be picked up.
    assert _check(settings, [(_UnregisteredJob(), "@daily")]) == [
        "jobs.schedule.unregistered_class"
    ]


def test_duplicate_entries(settings):
    assert _check(settings, [(JOB, "@daily"), (JOB, "@daily")]) == [
        "jobs.schedule.duplicate_entry"
    ]


def test_schedule_that_never_matches_warns(settings):
    # A warning, not an error — a valid sparse schedule (e.g. Feb 29) can
    # exceed next()'s 500-day scan depending on the deploy date, and that
    # must not block a deploy.
    settings.JOBS_SCHEDULE = [(JOB, "0 0 30 2 *")]
    results = CheckJobsSchedule().run()
    assert [result.id for result in results] == ["jobs.schedule.never_matches"]
    assert results[0].warning


def test_concurrency_key_too_long(settings):
    assert _check(settings, [(_LongKeyJob(), "@daily")]) == [
        "jobs.schedule.concurrency_key_too_long"
    ]


def test_broken_entries_are_all_reported(settings):
    ids = _check(
        settings,
        [
            ("app.gone.RemovedJob", "@daily"),
            (JOB, "* * * *"),
            (JOB, "@daily"),  # valid — doesn't mask or get masked
        ],
    )
    assert ids == ["jobs.schedule.unregistered_class", "jobs.schedule.invalid"]
