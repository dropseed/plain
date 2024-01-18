from datetime import timedelta

from bolt.admin import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelViewset,
    register_viewset,
)
from bolt.admin.cards import Card
from bolt.admin.dates import DatetimeRangeAliases
from bolt.http import HttpResponseRedirect
from bolt.runtime import settings

from .models import Job, JobRequest, JobResult


def _td_format(td_object):
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
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return ", ".join(strings)


class SuccessfulJobsCard(Card):
    title = "Successful Jobs"
    text = "View"

    def get_number(self):
        return (
            JobResult.objects.successful()
            .filter(created_at__range=self.datetime_range.as_tuple())
            .count()
        )

    def get_link(self):
        return JobResultViewset.ListView.get_absolute_url() + "?filter=Successful"


class ErroredJobsCard(Card):
    title = "Errored Jobs"
    text = "View"

    def get_number(self):
        return (
            JobResult.objects.errored()
            .filter(created_at__range=self.datetime_range.as_tuple())
            .count()
        )

    def get_link(self):
        return JobResultViewset.ListView.get_absolute_url() + "?filter=Errored"


class LostJobsCard(Card):
    title = "Lost Jobs"
    text = "View"  # TODO make not required - just an icon?

    def get_description(self):
        delta = timedelta(seconds=settings.JOBS_LOST_AFTER)
        return f"Jobs are considered lost after {_td_format(delta)}"

    def get_number(self):
        return (
            JobResult.objects.lost()
            .filter(created_at__range=self.datetime_range.as_tuple())
            .count()
        )

    def get_link(self):
        return JobResultViewset.ListView.get_absolute_url() + "?filter=Lost"


class RetriedJobsCard(Card):
    title = "Retried Jobs"
    text = "View"  # TODO make not required - just an icon?

    def get_number(self):
        return (
            JobResult.objects.retried()
            .filter(created_at__range=self.datetime_range.as_tuple())
            .count()
        )

    def get_link(self):
        return JobResultViewset.ListView.get_absolute_url() + "?filter=Retried"


@register_viewset
class JobRequestViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        model = JobRequest
        fields = ["id", "job_class", "priority", "created_at"]

    class DetailView(AdminModelDetailView):
        model = JobRequest


@register_viewset
class JobViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        model = Job
        fields = ["id", "job_class", "priority", "created_at", "started_at"]
        actions = ["Delete"]

        def perform_action(self, action: str, target_pks: list):
            if action == "Delete":
                Job.objects.filter(pk__in=target_pks).delete()

    class DetailView(AdminModelDetailView):
        model = Job


@register_viewset
class JobResultViewset(AdminModelViewset):
    class ListView(AdminModelListView):
        nav_section = "Jobs"
        model = JobResult
        fields = [
            "id",
            "job_class",
            "priority",
            "created_at",
            "status",
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
            "Lost",
            "Retried",
        ]
        actions = [
            "Retry",
        ]
        allow_global_search = False
        default_datetime_range = DatetimeRangeAliases.LAST_7_DAYS

        def get_description(self):
            delta = timedelta(seconds=settings.JOBS_CLEARABLE_AFTER)
            return f"Jobs are cleared after {_td_format(delta)}"

        def get_initial_queryset(self):
            queryset = super().get_initial_queryset()
            if self.filter == "Successful":
                return queryset.successful()
            if self.filter == "Errored":
                return queryset.errored()
            if self.filter == "Lost":
                return queryset.lost()
            if self.filter == "Retried":
                return queryset.retried()
            return queryset

        def get_fields(self):
            fields = super().get_fields()
            if self.filter == "Retried":
                fields.append("retries")
                fields.append("retry_attempt")
            return fields

        def perform_action(self, action: str, target_pks: list):
            if action == "Retry":
                for result in JobResult.objects.filter(pk__in=target_pks):
                    result.retry_job(delay=0)
            else:
                raise ValueError("Invalid action")

    class DetailView(AdminModelDetailView):
        model = JobResult

        def post(self):
            self.load_object()
            self.object.retry_job(delay=0)
            return HttpResponseRedirect(".")
