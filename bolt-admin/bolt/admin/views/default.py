from .base import AdminPageView


class AdminIndexView(AdminPageView):
    template_name = "bolt/admin/index.html"
    title = "Admin"
    slug = ""
