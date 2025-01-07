from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelViewset,
    register_viewset,
)

from .models import SupportFormEntry


@register_viewset
class PageviewStaff(StaffModelViewset):
    class ListView(StaffModelListView):
        model = SupportFormEntry
        nav_section = "Support"
        title = "Form entries"
        fields = ["user", "email", "name", "form_slug", "created_at"]

    class DetailView(StaffModelDetailView):
        model = SupportFormEntry
