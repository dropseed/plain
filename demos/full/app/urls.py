from plain.admin.urls import AdminRouter
from plain.assets.urls import AssetsRouter
from plain.auth.views import LogoutView
from plain.passwords.views import PasswordLoginView
from plain.urls import Router, include, path
from plain.views import View


class LoginView(PasswordLoginView):
    pass


class IndexView(View):
    def get(self):
        return "Index!"


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        include("assets/", AssetsRouter),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        path("", IndexView, name="index"),
    ]
