from __future__ import annotations

from datetime import timedelta
from typing import Any

from plain import postgres
from plain.admin.cards import Card, TrendCard
from plain.admin.views import (
    AdminListView,
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_view,
    register_viewset,
)
from plain.http import RedirectResponse
from plain.postgres.expressions import Case, When
from plain.runtime import settings

from .models import (
    JobProcess,
    JobRequest,
    JobResult,
    JobResultQuerySet,
    ScheduleState,
    WorkerHeartbeat,
    heartbeat_cutoff,
)
from .scheduling import (
    load_schedule_entry,
    schedule_entry_display,
    schedule_entry_key,
)


def _td_format(td_object: timedelta) -> str:
    seconds = int(td_object.total_seconds())
    periods = [
        ("year", 60 * 60 * 24 * 365),
        ("month", 60 * 60 * 24 * 30),
        ("day", 60 * 60 * 24),
        ("hour", 60 * 60),
        ("minute", 60),
        ("second", 1),
    ]

    strings = []
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            has_s = "s" if period_value > 1 else ""
            strings.append(f"{period_value} {period_name}{has_s}")

    return ", ".join(strings)


class JobResultsTrendCard(TrendCard):
    title = "Results trend"
    model = JobResult
    datetime_field = "created_at"
    size = TrendCard.Sizes.FULL
    group_field = "status"
    group_labels = {
        "SUCCESSFUL": "Successful",
        "ERRORED": "Errored",
        "CANCELLED": "Cancelled",
        "DEFERRED": "Deferred",
        "LOST": "Lost",
    }
    group_colors = {
        "SUCCESSFUL": "var(--success)",
        "ERRORED": "var(--danger)",
        "CANCELLED": "var(--muted-foreground)",
        "DEFERRED": "var(--info)",
        "LOST": "var(--warning)",
    }


class SuccessfulJobsCard(Card):
    title = "Successful"
    text = "View"

    def get_metric(self) -> int:
        return JobResult.query.successful().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Successful"


class ErroredJobsCard(Card):
    title = "Errored"
    text = "View"

    def get_metric(self) -> int:
        return JobResult.query.errored().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Errored"


class LostJobsCard(Card):
    title = "Lost"
    text = "View"  # TODO make not required - just an icon?

    def get_description(self) -> str:
        delta = timedelta(seconds=settings.JOBS_HEARTBEAT_TIMEOUT)
        return (
            f"Jobs are considered lost when their worker stops heartbeating "
            f"for more than {_td_format(delta)}"
        )

    def get_metric(self) -> int:
        return JobResult.query.lost().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Lost"


class RetriedJobsCard(Card):
    title = "Retried"
    text = "View"  # TODO make not required - just an icon?

    def get_metric(self) -> int:
        return JobResult.query.retried().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Retried"


class WaitingJobsCard(Card):
    title = "Waiting"

    def get_metric(self) -> int:
        return JobProcess.query.waiting().count()


class RunningJobsCard(Card):
    title = "Running"

    def get_metric(self) -> int:
        return JobProcess.query.running().count()


class ActiveWorkersCard(Card):
    title = "Active workers"
    text = "View"

    def get_description(self) -> str:
        delta = timedelta(seconds=settings.JOBS_HEARTBEAT_TIMEOUT)
        return f"Workers whose heartbeat is within the last {_td_format(delta)}."

    def get_metric(self) -> int:
        return WorkerHeartbeat.query.filter(
            last_heartbeat_at__gte=heartbeat_cutoff()
        ).count()

    def get_link(self) -> str:
        return WorkerHeartbeatViewset.ListView.get_view_url()


class StaleWorkersCard(Card):
    title = "Stale workers"
    text = "View"

    def get_description(self) -> str:
        delta = timedelta(seconds=settings.JOBS_HEARTBEAT_TIMEOUT)
        return (
            f"Workers whose heartbeat is older than {_td_format(delta)}. "
            f"Their in-flight jobs are about to be rescued as Lost."
        )

    def get_metric(self) -> int:
        return WorkerHeartbeat.query.filter(
            last_heartbeat_at__lt=heartbeat_cutoff()
        ).count()

    def get_link(self) -> str:
        return WorkerHeartbeatViewset.ListView.get_view_url() + "?display=Stale"


@register_view
class ScheduleView(AdminListView):
    nav_section = "Jobs"
    nav_icon = "calendar-week"
    title = "Schedule"
    description = "JOBS_SCHEDULE entries with their next slot and the last one handled."
    path = "jobschedule/"
    fields = ["job", "schedule", "queue", "next_slot", "last_enqueued_slot"]

    def get_initial_objects(self) -> list[dict[str, Any]]:
        ledger = dict(
            ScheduleState.query.values_list("schedule_key", "last_enqueued_slot")
        )

        rows = []
        for entry in settings.JOBS_SCHEDULE:
            try:
                job, schedule = load_schedule_entry(entry)
                rows.append(
                    {
                        "job": schedule_entry_display(job),
                        "schedule": str(schedule),
                        "queue": job.default_queue(),
                        # next() raises for a schedule that can never match
                        "next_slot": schedule.next(),
                        "last_enqueued_slot": ledger.get(
                            schedule_entry_key(job, schedule)
                        ),
                    }
                )
            except Exception as e:
                # Render the broken entry instead of failing the whole page —
                # this is exactly the state an operator is here to diagnose.
                # repr(entry) is safe for any malformed shape.
                rows.append(
                    {
                        "job": f"{entry!r} ({type(e).__name__})",
                        "schedule": "",
                        "queue": "",
                        "next_slot": None,
                        "last_enqueued_slot": None,
                    }
                )

        return rows


@register_viewset
class JobRequestViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        nav_icon = "inbox"
        model = JobRequest
        title = "Requests"
        description = "Jobs waiting to be picked up by a worker."
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "start_at",
            "concurrency_key",
        ]
        actions = ["Delete"]
        queryset_order = ["-priority", "-start_at", "-created_at"]

        def perform_action(self, action: str, target_ids: list[int]) -> None:
            if action == "Delete":
                JobRequest.query.filter(id__in=target_ids).delete()

    class DetailView(AdminModelDetailView):
        model = JobRequest
        title = "Request"


@register_viewset
class JobProcessViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        nav_icon = "gear"
        model = JobProcess
        title = "Processes"
        description = "Jobs currently being processed by a worker."
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "started_at",
            "concurrency_key",
        ]
        actions = ["Delete"]
        cards = [
            WaitingJobsCard,
            RunningJobsCard,
            ActiveWorkersCard,
            StaleWorkersCard,
        ]

        def perform_action(self, action: str, target_ids: list[int]) -> None:
            if action == "Delete":
                JobProcess.query.filter(id__in=target_ids).delete()

    class DetailView(AdminModelDetailView):
        model = JobProcess
        title = "Process"


@register_viewset
class JobResultViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        nav_icon = "clipboard-check"
        model = JobResult
        title = "Results"
        description = "Completed jobs with their success/failure status."
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "status",
            "retried",
            "is_retry",
        ]
        field_templates = {
            "status": "jobs/values/job_status.html",
        }
        search_fields = [
            "uuid",
            "job_process_uuid",
            "job_request_uuid",
            "job_class",
        ]
        cards = [
            JobResultsTrendCard,
            SuccessfulJobsCard,
            ErroredJobsCard,
            LostJobsCard,
            RetriedJobsCard,
        ]
        filters = [
            "Successful",
            "Errored",
            "Cancelled",
            "Lost",
            "Retried",
        ]
        actions = [
            "Retry",
        ]

        def get_initial_queryset(self) -> JobResultQuerySet:
            queryset: JobResultQuerySet = super().get_initial_queryset()  # ty: ignore[invalid-assignment]
            return queryset.annotate(
                retried=Case(
                    When(retry_job_request_uuid__isnull=False, then=True),
                    default=False,
                    output_field=postgres.BooleanField(),
                ),
                is_retry=Case(
                    When(retry_attempt__gt=0, then=True),
                    default=False,
                    output_field=postgres.BooleanField(),
                ),
            )

        def filter_queryset(self, queryset: JobResultQuerySet) -> JobResultQuerySet:
            if self.filter == "Successful":
                return queryset.successful()
            if self.filter == "Errored":
                return queryset.errored()
            if self.filter == "Cancelled":
                return queryset.cancelled()
            if self.filter == "Lost":
                return queryset.lost()
            if self.filter == "Retried":
                return queryset.retried()
            return queryset

        def get_fields(self) -> list[str]:
            fields = super().get_fields()
            if self.filter == "Retried":
                fields.append("retries")
                fields.append("retry_attempt")
            return fields

        def perform_action(self, action: str, target_ids: list[int]) -> None:
            if action == "Retry":
                for result in JobResult.query.filter(id__in=target_ids):
                    result.retry_job(delay=0)
            else:
                raise ValueError("Invalid action")

    class DetailView(AdminModelDetailView):
        model = JobResult
        title = "Result"

        def post(self) -> RedirectResponse:
            self.object.retry_job(delay=0)
            return RedirectResponse(".")


@register_viewset
class WorkerHeartbeatViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        nav_icon = "heart-pulse"
        model = WorkerHeartbeat
        title = "Workers"
        description = (
            "Live worker processes. Each row is refreshed while its worker is "
            "running and deleted on clean shutdown."
        )
        fields = [
            "worker_id",
            "hostname",
            "pid",
            "queues",
            "started_at",
            "last_heartbeat_at",
            "stale",
        ]
        search_fields = [
            "worker_id",
            "hostname",
        ]
        filters = [
            "Active",
            "Stale",
        ]
        queryset_order = ["-last_heartbeat_at"]

        def get_initial_queryset(self) -> postgres.QuerySet[WorkerHeartbeat]:
            queryset = super().get_initial_queryset()
            return queryset.annotate(
                stale=Case(
                    When(last_heartbeat_at__lt=heartbeat_cutoff(), then=True),
                    default=False,
                    output_field=postgres.BooleanField(),
                ),
            )

        def filter_queryset(
            self, queryset: postgres.QuerySet[WorkerHeartbeat]
        ) -> postgres.QuerySet[WorkerHeartbeat]:
            cutoff = heartbeat_cutoff()
            if self.filter == "Active":
                return queryset.filter(last_heartbeat_at__gte=cutoff)
            if self.filter == "Stale":
                return queryset.filter(last_heartbeat_at__lt=cutoff)
            return queryset

    class DetailView(AdminModelDetailView):
        model = WorkerHeartbeat
        title = "Worker"
