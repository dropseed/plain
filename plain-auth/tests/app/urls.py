from plain.auth.views import AuthViewMixin
from plain.urls import Router, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "login"


class ProtectedView(AuthViewMixin, View):
    def get(self):
        return "protected"


class OpenView(AuthViewMixin, View):
    login_required = False

    def get(self):
        return "open"


class AdminView(AuthViewMixin, View):
    admin_required = True

    def get(self):
        return "admin"


class NoLoginUrlView(AuthViewMixin, View):
    login_url = None

    def get(self):
        return "none"


class AppRouter(Router):
    namespace = ""
    urls = [
        path("login/", LoginView, name="login"),
        path("protected/", ProtectedView, name="protected"),
        path("open/", OpenView, name="open"),
        path("admin/", AdminView, name="admin"),
        path("nolink/", NoLoginUrlView, name="nolink"),
    ]
