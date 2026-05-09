# from plain.admin.cards import Card
from plain.admin.views import (
    AdminModelCreateView,
    AdminModelDeleteView,
    AdminModelDetailView,
    AdminModelListView,
    AdminModelUpdateView,
    AdminViewset,
    register_viewset,
)
from plain.postgres.modelschema import ModelSchema

from .models import NotFoundLog, Redirect, RedirectLog


class RedirectSchema(ModelSchema):
    model = Redirect

    from_pattern: str
    to_pattern: str
    http_status: int
    order: int
    enabled: bool
    is_regex: bool


@register_viewset
class RedirectAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Redirect
        nav_section = "Redirection"
        nav_icon = "signpost-split"
        title = "Redirects"
        description = "URL redirect rules processed in order."
        fields = ["from_pattern", "to_pattern", "http_status", "order", "enabled"]
        search_fields = ["from_pattern", "to_pattern"]

    class DetailView(AdminModelDetailView):
        model = Redirect

    class CreateView(AdminModelCreateView):
        model = Redirect
        schema_class = RedirectSchema
        template_name = "admin/plainredirection/redirect_form.html"

    class UpdateView(AdminModelUpdateView):
        model = Redirect
        schema_class = RedirectSchema
        template_name = "admin/plainredirection/redirect_form.html"

    class DeleteView(AdminModelDeleteView):
        model = Redirect


@register_viewset
class RedirectLogAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = RedirectLog
        nav_section = "Redirection"
        nav_icon = "arrow-repeat"
        title = "Redirect logs"
        fields = [
            "created_at",
            "from_url",
            "to_url",
            "http_status",
            "user_agent",
            "ip_address",
            "referrer",
        ]
        search_fields = ["from_url", "to_url", "user_agent", "ip_address", "referrer"]

    class DetailView(AdminModelDetailView):
        model = RedirectLog


@register_viewset
class NotFoundLogAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = NotFoundLog
        nav_section = "Redirection"
        nav_icon = "exclamation-circle"
        title = "404 logs"
        description = "URLs that returned 404 - useful for finding broken links."
        fields = ["created_at", "url", "user_agent", "ip_address", "referrer"]
        search_fields = ["url", "user_agent", "ip_address", "referrer"]

    class DetailView(AdminModelDetailView):
        model = NotFoundLog
