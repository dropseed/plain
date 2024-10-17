from plain.auth import login, logout
from plain.http import ResponseRedirect
from plain.runtime import settings
from plain.urls import reverse, reverse_lazy
from plain.views import FormView, TemplateView, View

from .forms import LoginLinkForm
from .links import (
    LoginLinkChanged,
    LoginLinkExpired,
    LoginLinkInvalid,
    get_link_token_user,
)


class LoginLinkFormView(FormView):
    form_class = LoginLinkForm
    success_url = reverse_lazy("loginlink:sent")

    def get(self):
        # Redirect if the user is already logged in
        if self.request.user:
            return ResponseRedirect(self.success_url)

        return super().get()

    def form_valid(self, form):
        form.maybe_send_link(self.request)
        return super().form_valid(form)


class LoginLinkSentView(TemplateView):
    template_name = "loginlink/sent.html"

    def get(self):
        # Redirect if the user is already logged in
        if self.request.user:
            return ResponseRedirect("/")

        return super().get()


class LoginLinkFailedView(TemplateView):
    template_name = "loginlink/failed.html"

    def get_template_context(self):
        context = super().get_template_context()
        context["error"] = self.request.GET.get("error")
        context["login_url"] = reverse(settings.AUTH_LOGIN_URL)
        return context


class LoginLinkLoginView(View):
    success_url = "/"

    def get(self):
        # If they're logged in, log them out and process the link again
        if self.request.user:
            logout(self.request)

        token = self.url_kwargs["token"]

        try:
            user = get_link_token_user(token)
        except LoginLinkExpired:
            return ResponseRedirect(reverse("loginlink:failed") + "?error=expired")
        except LoginLinkInvalid:
            return ResponseRedirect(reverse("loginlink:failed") + "?error=invalid")
        except LoginLinkChanged:
            return ResponseRedirect(reverse("loginlink:failed") + "?error=changed")

        login(self.request, user)

        return ResponseRedirect(self.success_url)