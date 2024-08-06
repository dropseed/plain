from functools import cached_property

from plain.models.forms import ModelForm
from plain.staff.cards import Card
from plain.staff.views import (
    StaffModelDetailView,
    StaffModelListView,
    StaffModelUpdateView,
    StaffModelViewset,
    register_viewset,
)

from .models import Flag, FlagResult


class UnusedFlagsCard(Card):
    title = "Unused Flags"

    @cached_property
    def flag_errors(self):
        return Flag.check(databases=["default"])

    def get_number(self):
        return len(self.flag_errors)

    def get_text(self):
        return "\n".join(str(e.msg) for e in self.flag_errors)


@register_viewset
class FlagStaff(StaffModelViewset):
    class ListView(StaffModelListView):
        model = Flag
        fields = ["name", "enabled", "created_at__date", "used_at__date", "uuid"]
        search_fields = ["name", "description"]
        cards = [UnusedFlagsCard]
        nav_section = "Feature flags"

    class DetailView(StaffModelDetailView):
        model = Flag


class FlagResultForm(ModelForm):
    class Meta:
        model = FlagResult
        fields = ["key", "value"]


@register_viewset
class FlagResultStaff(StaffModelViewset):
    class ListView(StaffModelListView):
        model = FlagResult
        title = "Flag results"
        fields = [
            "flag",
            "key",
            "value",
            "created_at__date",
            "updated_at__date",
            "uuid",
        ]
        search_fields = ["flag__name", "key"]
        nav_section = "Feature flags"

        def get_initial_queryset(self):
            return self.model.objects.all().select_related("flag")

    class DetailView(StaffModelDetailView):
        model = FlagResult
        title = "Flag result"

    class UpdateView(StaffModelUpdateView):
        model = FlagResult
        title = "Update flag result"
        form_class = FlagResultForm
