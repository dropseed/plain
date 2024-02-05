from bolt.auth.views import AuthViewMixin
from bolt.http import HttpResponseBadRequest, HttpResponseRedirect
from bolt.templates import jinja
from bolt.views import View

from .exceptions import (
    OAuthStateMismatchError,
    OAuthUserAlreadyExistsError,
)
from .providers import get_oauth_provider_instance


class OAuthLoginView(View):
    def post(self):
        request = self.request
        provider = self.url_kwargs["provider"]
        if request.user:
            return HttpResponseRedirect("/")

        provider_instance = get_oauth_provider_instance(provider_key=provider)
        return provider_instance.handle_login_request(request=request)


class OAuthCallbackView(View):
    """
    The callback view is used for signup, login, and connect.
    """

    def get(self):
        request = self.request
        provider = self.url_kwargs["provider"]
        provider_instance = get_oauth_provider_instance(provider_key=provider)
        try:
            return provider_instance.handle_callback_request(request=request)
        except OAuthUserAlreadyExistsError:
            template = jinja.get_template("oauth/error.html")
            return HttpResponseBadRequest(
                template.render(
                    {
                        "oauth_error": "A user already exists with this email address. Please log in first and then connect this OAuth provider to the existing account."
                    }
                )
            )
        except OAuthStateMismatchError:
            template = jinja.get_template("oauth/error.html")
            return HttpResponseBadRequest(
                template.render(
                    {
                        "oauth_error": "The state parameter did not match. Please try again."
                    }
                )
            )


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
        #         status=400,
        #     )
