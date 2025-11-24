from plain.auth.views import AuthView
from plain.urls import Router, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "login"


class ProtectedView(AuthView):
    login_required = True

    def get(self):
        return "protected"


class OpenView(AuthView):
    # login_required = False

    def get(self):
        return "open"


class AdminView(AuthView):
    admin_required = True

    def get(self):
        return "admin"


class NoLoginUrlView(AuthView):
    login_required = True
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
