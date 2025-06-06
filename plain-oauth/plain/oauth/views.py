import logging

from plain.auth.views import AuthViewMixin
from plain.http import ResponseRedirect
from plain.views import TemplateView, View

from .exceptions import (
    OAuthError,
)
from .providers import get_oauth_provider_instance

logger = logging.getLogger(__name__)


class OAuthLoginView(View):
    def post(self):
        request = self.request
        provider = self.url_kwargs["provider"]
        if request.user:
            return ResponseRedirect("/")

        provider_instance = get_oauth_provider_instance(provider_key=provider)
        return provider_instance.handle_login_request(request=request)


class OAuthCallbackView(TemplateView):
    """
    The callback view is used for signup, login, and connect.
    """

    template_name = "oauth/callback.html"

    def get(self):
        provider = self.url_kwargs["provider"]
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        try:
            return provider_instance.handle_callback_request(request=self.request)
        except OAuthError as e:
            logger.exception("OAuth error")
            self.oauth_error = e

            response = super().get()
            response.status_code = 400
            return response

    def get_template_context(self) -> dict:
        context = super().get_template_context()
        context["oauth_error"] = getattr(self, "oauth_error", None)
        return context


class OAuthConnectView(AuthViewMixin, View):
    def post(self):
        request = self.request
        provider = self.url_kwargs["provider"]
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        return provider_instance.handle_connect_request(request=request)


class OAuthDisconnectView(AuthViewMixin, View):
    def post(self):
        request = self.request
        provider = self.url_kwargs["provider"]
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        # try:
        return provider_instance.handle_disconnect_request(request=request)
        # except OAuthCannotDisconnectError:
        #     return render(
        #         request,
        #         "oauth/error.html",
        #         {
        #             "oauth_error": "This connection can't be removed. You must have a usable password or at least one active connection."
        #         },
        #         status_code=400,
        #     )
