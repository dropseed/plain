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

from .models import User


class UserForm(ModelForm):
    username = model_field(User.username)
    is_admin = model_field(User.is_admin)


@register_viewset
class UserAdmin(AdminViewset):
    class ListView(AdminModelListView):
        model = User
        title = "Users"
        nav_section = "Users"
        fields = ["id", "username", "is_admin"]

    class DetailView(AdminModelDetailView):
        model = User

    class CreateView(AdminModelCreateView):
        model = User
        form_class = UserForm
        template_name = "admin/users/user_form.html"

    class UpdateView(AdminModelUpdateView):
        model = User
        form_class = UserForm
        template_name = "admin/users/user_form.html"

    class DeleteView(AdminModelDeleteView):
        model = User
