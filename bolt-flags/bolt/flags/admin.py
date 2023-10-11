from functools import cached_property

from bolt.admin import AdminCard, AdminModelViewset, register_model
from bolt.db.forms import ModelForm

from .models import Flag, FlagResult


class UnusedFlagsCard(AdminCard):
    title = "Unused Flags"

    @cached_property
    def flag_errors(self):
        return Flag.check(databases=["default"])

    def get_number(self):
        return len(self.flag_errors)

    def get_text(self):
        return "\n".join(str(e.msg) for e in self.flag_errors)


@register_model
class FlagAdmin(AdminModelViewset):
    model = Flag
    list_fields = ["name", "enabled", "created_at__date", "used_at__date", "uuid"]
    search_fields = ["name", "description"]
    list_cards = [UnusedFlagsCard]


class FlagResultForm(ModelForm):
    class Meta:
        model = FlagResult
        fields = ["key", "value"]


@register_model
class FlagResultAdmin(AdminModelViewset):
    model = FlagResult
    list_fields = [
        "flag",
        "key",
        "value",
        "created_at__date",
        "updated_at__date",
        "uuid",
    ]
    search_fields = ["flag__name", "key"]
    form_class = FlagResultForm

    def get_list_queryset(self):
        return self.model.objects.all().select_related("flag")
