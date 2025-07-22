from functools import cached_property

from plain.admin.toolbar import ToolbarPanel, register_toolbar_panel
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)

from .core import Observer
from .models import Span, Trace


@register_viewset
class TraceViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observer"
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

        # def perform_action(self, action: str, target_ids: list):
        #     if action == "Delete":
        #         Trace.objects.filter(id__in=target_ids).delete()

    class DetailView(AdminModelDetailView):
        model = Trace


@register_viewset
class SpanViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Observer"
        model = Span
        fields = [
            "name",
            "kind",
            "status",
            "span_id",
            "parent_id",
            "start_time",
        ]
        queryset_order = ["-id"]
        allow_global_search = False
        displays = ["Parents only"]
        search_fields = ["name", "span_id", "parent_id"]

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
class ObserverToolbarPanel(ToolbarPanel):
    name = "Observer"
    template_name = "toolbar/observer.html"
    button_template_name = "toolbar/observer_button.html"

    @cached_property
    def observer(self):
        """Get the Observer instance for this request."""
        return Observer(self.request)

    def get_template_context(self):
        context = super().get_template_context()
        context["observer"] = self.observer
        return context
