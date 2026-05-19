from plain.urls import Router, path
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
        path("login", LoginView, name="login"),
        path("logout", LogoutView, name="logout"),
    ]
