from django.contrib import admin
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LogoutView
from bolt.urls import include, path
from django.views.generic import TemplateView

from bolt.oauth.providers import get_provider_keys


class LoggedInView(LoginRequiredMixin, TemplateView):
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
