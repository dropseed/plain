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
from plain.postgres.forms import ModelForm, model_field

from .models import NotFoundLog, Redirect, RedirectLog


class RedirectForm(ModelForm):
    from_pattern = model_field(Redirect.from_pattern)
    to_pattern = model_field(Redirect.to_pattern)
    http_status = model_field(Redirect.http_status)
    order = model_field(Redirect.order)
    enabled = model_field(Redirect.enabled)
    is_regex = model_field(Redirect.is_regex)


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
        form_class = RedirectForm
        template_name = "admin/plainredirection/redirect_form.html"

    class UpdateView(AdminModelUpdateView):
        model = Redirect
        form_class = RedirectForm
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
