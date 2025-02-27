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
from plain.models.forms import ModelForm

from .models import NotFoundLog, Redirect, RedirectLog


class RedirectForm(ModelForm):
    class Meta:
        model = Redirect
        fields = [
            "from_pattern",
            "to_pattern",
            "http_status",
            "order",
            "enabled",
            "is_regex",
        ]


@register_viewset
class RedirectAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Redirect
        nav_section = "Redirection"
        title = "Redirects"
        fields = ["from_pattern", "to_pattern", "http_status", "order", "enabled"]
        search_fields = ["from_pattern", "to_pattern"]
        allow_global_search = False

    class DetailView(AdminModelDetailView):
        model = Redirect

    class CreateView(AdminModelCreateView):
        model = Redirect
        form_class = RedirectForm

    class UpdateView(AdminModelUpdateView):
        model = Redirect
        form_class = RedirectForm

    class DeleteView(AdminModelDeleteView):
        model = Redirect


@register_viewset
class RedirectLogAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = RedirectLog
        nav_section = "Redirection"
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
        allow_global_search = False

    class DetailView(AdminModelDetailView):
        model = RedirectLog


@register_viewset
class NotFoundLogAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = NotFoundLog
        nav_section = "Redirection"
        title = "404 logs"
        fields = ["created_at", "url", "user_agent", "ip_address", "referrer"]
        search_fields = ["url", "user_agent", "ip_address", "referrer"]
        allow_global_search = False

    class DetailView(AdminModelDetailView):
        model = NotFoundLog
