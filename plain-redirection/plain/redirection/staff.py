from plain.models.forms import ModelForm

# from plain.staff.cards import Card
from plain.staff.views import (
    StaffModelCreateView,
    StaffModelDeleteView,
    StaffModelDetailView,
    StaffModelListView,
    StaffModelUpdateView,
    StaffViewset,
    register_viewset,
)

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
class RedirectStaff(StaffViewset):
    class ListView(StaffModelListView):
        model = Redirect
        nav_section = "Redirection"
        title = "Redirects"
        fields = ["from_pattern", "to_pattern", "http_status", "order", "enabled"]
        search_fields = ["from_pattern", "to_pattern"]
        allow_global_search = False

    class DetailView(StaffModelDetailView):
        model = Redirect

    class CreateView(StaffModelCreateView):
        model = Redirect
        form_class = RedirectForm

    class UpdateView(StaffModelUpdateView):
        model = Redirect
        form_class = RedirectForm

    class DeleteView(StaffModelDeleteView):
        model = Redirect


@register_viewset
class RedirectLogStaff(StaffViewset):
    class ListView(StaffModelListView):
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
            "referer",
        ]
        search_fields = ["from_url", "to_url", "user_agent", "ip_address", "referer"]
        allow_global_search = False

    class DetailView(StaffModelDetailView):
        model = RedirectLog


@register_viewset
class NotFoundLogStaff(StaffViewset):
    class ListView(StaffModelListView):
        model = NotFoundLog
        nav_section = "Redirection"
        title = "404 logs"
        fields = ["created_at", "url", "user_agent", "ip_address", "referer"]
        search_fields = ["url", "user_agent", "ip_address", "referer"]
        allow_global_search = False

    class DetailView(StaffModelDetailView):
        model = NotFoundLog
