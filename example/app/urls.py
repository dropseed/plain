from plain.admin.urls import AdminRouter
from plain.assets.urls import AssetsRouter
from plain.auth.views import LogoutView
from plain.observer.urls import ObserverRouter
from plain.passwords.views import PasswordLoginView
from plain.urls import Router, include, path
from plain.views import TemplateView


class LoginView(PasswordLoginView):
    template_name = "login.html"


class IndexView(TemplateView):
    template_name = "index.html"


class ErrorView(TemplateView):
    template_name = "index.html"

    def get(self):
        text = "This is a test exception to demonstrate the toolbar"
        raise ValueError(text)


class AppRouter(Router):
    namespace = ""
    urls = [
        include("admin/", AdminRouter),
        include("assets/", AssetsRouter),
        include("observer/", ObserverRouter),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        path("error/", ErrorView, name="error"),
        path("", IndexView, name="index"),
    ]
