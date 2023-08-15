from .base import AdminPageView


class AdminIndexView(AdminPageView):
    template_name = "admin/index.html"
    title = "Admin"
    slug = ""
