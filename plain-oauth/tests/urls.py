from plain.auth.views import AuthViewMixin, LogoutView
from plain.oauth.providers import get_provider_keys
from plain.staff import admin
from plain.urls import include, path
from plain.views import TemplateView


class LoggedInView(AuthViewMixin, TemplateView):
    template_name = "index.html"

    def get_context(self, **kwargs):
        context = super().get_context(**kwargs)
        context["oauth_provider_keys"] = get_provider_keys()
        return context


class LoginView(TemplateView):
    template_name = "login.html"


urlpatterns = [
    path("admin", admin.site.urls),
    path("oauth/", include("plain.oauth.urls")),
    path("login/", LoginView, name="login"),
    path("logout/", LogoutView, name="logout"),
    path("", LoggedInView),
]
