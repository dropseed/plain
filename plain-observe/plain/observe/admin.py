from plain.admin.toolbar import ToolbarPanel, register_toolbar_panel
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .models import Span, Trace


@register_viewset
class TraceViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observe"
        model = Trace
        fields = [
            "trace_id",
            "request_id",
            "session_id",
            "user_id",
            "start_time",
        ]
        allow_global_search = False
        # Actually want a button to delete ALL! not possible yet
        # actions = ["Delete"]

        # def perform_action(self, action: str, target_pks: list):
        #     if action == "Delete":
        #         Trace.objects.filter(id__in=target_pks).delete()

    class DetailView(AdminModelDetailView):
        model = Trace
        # title = "Cached item"


@register_viewset
class SpanViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observe"
        model = Span
        fields = [
            "name",
            "kind",
            "span_id",
            "parent_id",
            "start_time",
        ]
        queryset_order = ["-pk"]
        allow_global_search = False
        displays = ["Parents only"]

        def get_objects(self):
            return (
                super()
                .get_objects()
                .only(
                    "name",
                    "kind",
                    "span_id",
                    "parent_id",
                    "start_time",
                )
            )

        def get_initial_queryset(self):
            queryset = super().get_initial_queryset()
            if self.display == "Parents only":
                queryset = queryset.filter(parent_id="")
            return queryset

    class DetailView(AdminModelDetailView):
        model = Span


@register_toolbar_panel
class ObservabilityToolbarPanel(ToolbarPanel):
    name = "Observability"
    template_name = "toolbar/observability.html"
