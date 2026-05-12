from plain.auth.views import AuthView, LogoutView
from plain.oauth.providers import get_provider_keys
from plain.oauth.urls import OAuthRouter
from plain.templates.views import TemplateView
from plain.urls import Router, include, path


class LoggedInView(AuthView, TemplateView):
    template_name = "index.html"
    login_required = True

    def get_template_context(self):
        context = super().get_template_context()
        context["oauth_provider_keys"] = get_provider_keys()
        return context


class LoginView(TemplateView):
    template_name = "login.html"


class AppRouter(Router):
    namespace = ""
    urls = [
        include("oauth/", OAuthRouter),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        path("", LoggedInView),
    ]
