from __future__ import annotations

from collections.abc import Sequence

from plain import models
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Log, Span, Trace


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
        queryset_order = ["-id"]
        filters = ["Parents only"]
        search_fields = ["name", "span_id", "parent_id"]
        actions = ["Delete"]

        def perform_action(self, action: str, target_ids: Sequence[int]) -> None:
            if action == "Delete":
                Span.query.filter(id__in=target_ids).delete()

        def get_initial_queryset(self) -> models.QuerySet:
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

        def filter_queryset(self, queryset: models.QuerySet) -> models.QuerySet:
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
        queryset_order = ["-timestamp"]
        search_fields = ["message", "level"]
        actions = ["Delete selected", "Delete all"]

        def perform_action(self, action: str, target_ids: Sequence[int]) -> None:
            if action == "Delete selected":
                Log.query.filter(id__in=target_ids).delete()
            elif action == "Delete all":
                Log.query.all().delete()

        def get_initial_queryset(self) -> models.QuerySet:
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
