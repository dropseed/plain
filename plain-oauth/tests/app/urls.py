import plain.oauth.urls
from plain.auth.views import AuthViewMixin, LogoutView
from plain.oauth.providers import get_provider_keys
from plain.urls import RouterBase, include, path, register_router
from plain.views import TemplateView


class LoggedInView(AuthViewMixin, TemplateView):
    template_name = "index.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["oauth_provider_keys"] = get_provider_keys()
        return context


class LoginView(TemplateView):
    template_name = "login.html"


@register_router
class Router(RouterBase):
    urls = [
        include("oauth/", plain.oauth.urls),
        path("login/", LoginView, name="login"),
        path("logout/", LogoutView, name="logout"),
        path("", LoggedInView),
    ]
