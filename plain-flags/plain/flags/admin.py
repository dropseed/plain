from functools import cached_property

from plain.admin.cards import Card
from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminModelUpdateView,
    AdminViewset,
    register_viewset,
)
from plain.models.forms import ModelForm

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
class FlagAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = Flag
        fields = ["name", "enabled", "created_at__date", "used_at__date", "uuid"]
        search_fields = ["name", "description"]
        cards = [UnusedFlagsCard]
        nav_section = "Feature flags"

    class DetailView(AdminModelDetailView):
        model = Flag


class FlagResultForm(ModelForm):
    class Meta:
        model = FlagResult
        fields = ["key", "value"]


@register_viewset
class FlagResultAdmin(AdminViewset):
    class ListView(AdminModelListView):
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

    class DetailView(AdminModelDetailView):
        model = FlagResult
        title = "Flag result"

    class UpdateView(AdminModelUpdateView):
        model = FlagResult
        title = "Update flag result"
        form_class = FlagResultForm
