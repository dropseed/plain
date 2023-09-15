from bolt.db.forms import ModelForm

from . import AdminModelViewset, register_model
from .models import Dashboard


class DashboardForm(ModelForm):
    class Meta:
        model = Dashboard
        fields = ["name", "description", "cards"]


@register_model
class DashboardAdmin(AdminModelViewset):
    model = Dashboard
    form_class = DashboardForm
    list_fields = [
        "name",
        "created_at__date",
        "updated_at__date",
    ]
