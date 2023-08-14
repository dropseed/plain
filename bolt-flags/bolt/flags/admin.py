from bolt.admin import AdminModelViewset, register_model
from bolt import forms

from .models import Flag, FlagResult


@register_model
class FlagAdmin(AdminModelViewset):
    model = Flag
    list_fields = ["name", "enabled", "created_at", "used_at", "uuid"]
    search_fields = ["name", "description"]



class FlagResultForm(forms.ModelForm):
    class Meta:
        model = FlagResult
        fields = ["key", "value"]


@register_model
class FlagResultAdmin(AdminModelViewset):
    model = FlagResult
    list_fields = ["flag", "key", "value", "created_at", "updated_at", "uuid"]
    search_fields = ["flag__name", "key"]
    form_class = FlagResultForm

    def get_list_queryset(self):
        return self.model.objects.all().select_related("flag")
