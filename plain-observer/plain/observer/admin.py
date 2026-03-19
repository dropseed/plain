from __future__ import annotations

from collections.abc import Sequence

from plain import postgres
from plain.admin.cards import TrendCard
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Log, Span, Trace


class TracesTrendCard(TrendCard):
    title = "Traces trend"
    model = Trace
    datetime_field = "start_time"
    size = TrendCard.Sizes.FULL
    group_field = "app_version"


class SpansTrendCard(TrendCard):
    title = "Spans trend"
    model = Span
    datetime_field = "start_time"
    size = TrendCard.Sizes.FULL
    group_field = "kind"


class LogsTrendCard(TrendCard):
    title = "Logs trend"
    model = Log
    datetime_field = "timestamp"
    size = TrendCard.Sizes.FULL
    group_field = "level"


@register_viewset
class TraceViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observer"
        nav_icon = "diagram-3"
        model = Trace
        description = "Request traces linking spans and logs together."
        fields = [
            "trace_id",
            "request_id",
            "session_id",
            "user_id",
            "start_time",
        ]
        cards = [TracesTrendCard]
        actions = ["Delete"]

        def perform_action(self, action: str, target_ids: Sequence[int]) -> None:
            if action == "Delete":
                Trace.query.filter(id__in=target_ids).delete()

    class DetailView(AdminModelDetailView):
        model = Trace


@register_viewset
class SpanViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observer"
        nav_icon = "activity"
        model = Span
        description = (
            "Individual operations within a trace (DB queries, HTTP calls, etc)."
        )
        fields = [
            "name",
            "kind",
            "status",
            "span_id",
            "parent_id",
            "start_time",
        ]
        field_templates = {
            "kind": "observer/values/span_kind.html",
            "status": "observer/values/span_status.html",
        }
        queryset_order = ["-id"]
        cards = [SpansTrendCard]
        filters = ["Parents only"]
        search_fields = ["name", "span_id", "parent_id"]
        actions = ["Delete"]

        def perform_action(self, action: str, target_ids: Sequence[int]) -> None:
            if action == "Delete":
                Span.query.filter(id__in=target_ids).delete()

        def get_initial_queryset(self) -> postgres.QuerySet:
            return (
                super()
                .get_initial_queryset()
                .only(
                    "name",
                    "kind",
                    "span_id",
                    "parent_id",
                    "start_time",
                )
            )

        def filter_queryset(self, queryset: postgres.QuerySet) -> postgres.QuerySet:
            if self.filter == "Parents only":
                return queryset.filter(parent_id="")
            return queryset

    class DetailView(AdminModelDetailView):
        model = Span


@register_viewset
class LogViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observer"
        nav_icon = "journal-text"
        model = Log
        description = "Application logs captured during request processing."
        fields = [
            "timestamp",
            "level",
            "message",
            "trace",
            "span",
        ]
        cards = [LogsTrendCard]
        queryset_order = ["-timestamp"]
        search_fields = ["message", "level"]
        actions = ["Delete selected", "Delete all"]

        def perform_action(self, action: str, target_ids: Sequence[int]) -> None:
            if action == "Delete selected":
                Log.query.filter(id__in=target_ids).delete()
            elif action == "Delete all":
                Log.query.all().delete()

        def get_initial_queryset(self) -> postgres.QuerySet:
            return (
                super()
                .get_initial_queryset()
                .select_related("trace", "span")
                .only(
                    "timestamp",
                    "level",
                    "message",
                    "span__span_id",
                    "trace__trace_id",
                )
            )

    class DetailView(AdminModelDetailView):
        model = Log
