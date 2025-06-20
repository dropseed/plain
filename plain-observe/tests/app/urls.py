from plain.admin.urls import AdminRouter
from plain.assets.urls import AssetsRouter
from plain.urls import Router, include, path
from plain.views import View


class LoginView(View):
    def get(self):
        return "Login!"


class LogoutView(View):
    def get(self):
        return "Logout!"


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        include("assets/", AssetsRouter),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
    ]
