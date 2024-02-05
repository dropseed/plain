from bolt import admin
from bolt.auth.views import AuthViewMixin, LogoutView
from bolt.oauth.providers import get_provider_keys
from bolt.urls import include, path
from bolt.views import TemplateView


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
    path("oauth/", include("bolt.oauth.urls")),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("", LoggedInView.as_view()),
]
