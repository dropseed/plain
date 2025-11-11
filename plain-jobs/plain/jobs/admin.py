from __future__ import annotations

from datetime import timedelta
from typing import Any

from plain import models
from plain.admin.cards import Card
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)
from plain.http import ResponseRedirect
from plain.models.expressions import Case, When
from plain.runtime import settings

from .models import JobProcess, JobRequest, JobResult


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


class SuccessfulJobsCard(Card):
    title = "Successful"
    text = "View"

    def get_number(self) -> int:
        return JobResult.query.successful().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Successful"


class ErroredJobsCard(Card):
    title = "Errored"
    text = "View"

    def get_number(self) -> int:
        return JobResult.query.errored().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Errored"


class LostJobsCard(Card):
    title = "Lost"
    text = "View"  # TODO make not required - just an icon?

    def get_description(self) -> str:
        delta = timedelta(seconds=settings.JOBS_TIMEOUT)
        return f"Jobs are considered lost after {_td_format(delta)}"

    def get_number(self) -> int:
        return JobResult.query.lost().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Lost"


class RetriedJobsCard(Card):
    title = "Retried"
    text = "View"  # TODO make not required - just an icon?

    def get_number(self) -> int:
        return JobResult.query.retried().count()

    def get_link(self) -> str:
        return JobResultViewset.ListView.get_view_url() + "?display=Retried"


class WaitingJobsCard(Card):
    title = "Waiting"

    def get_number(self) -> int:
        return JobProcess.query.waiting().count()


class RunningJobsCard(Card):
    title = "Running"

    def get_number(self) -> int:
        return JobProcess.query.running().count()


@register_viewset
class JobRequestViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        nav_icon = "gear"
        model = JobRequest
        title = "Requests"
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "start_at",
            "concurrency_key",
        ]
        actions = ["Delete"]
        queryset_order = ["priority", "-start_at", "-created_at"]

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
        nav_icon = "gear"
        model = JobResult
        title = "Results"
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "status",
            "retried",
            "is_retry",
        ]
        search_fields = [
            "uuid",
            "job_process_uuid",
            "job_request_uuid",
            "job_class",
        ]
        cards = [
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
        allow_global_search = False

        def get_initial_queryset(self) -> Any:
            queryset = super().get_initial_queryset()
            queryset = queryset.annotate(
                retried=Case(
                    When(retry_job_request_uuid__isnull=False, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
                is_retry=Case(
                    When(retry_attempt__gt=0, then=True),
                    default=False,
                    output_field=models.BooleanField(),
                ),
            )
            if self.preset == "Successful":
                return queryset.successful()
            if self.preset == "Errored":
                return queryset.errored()
            if self.preset == "Cancelled":
                return queryset.cancelled()
            if self.preset == "Lost":
                return queryset.lost()
            if self.preset == "Retried":
                return queryset.retried()
            return queryset

        def get_fields(self) -> list[str]:
            fields = super().get_fields()
            if self.preset == "Retried":
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

        def post(self) -> ResponseRedirect:
            self.object.retry_job(delay=0)
            return ResponseRedirect(".")
