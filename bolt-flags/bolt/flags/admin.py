from bolt.admin import AdminModelViewset, register_model
from bolt.db.forms import ModelForm

from .models import Flag, FlagResult


@register_model
class FlagAdmin(AdminModelViewset):
    model = Flag
    icon_name = "flag-fill"
    list_fields = ["name", "enabled", "created_at__date", "used_at__date", "uuid"]
    search_fields = ["name", "description"]


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
