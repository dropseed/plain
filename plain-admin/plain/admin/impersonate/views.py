from plain.auth.views import AuthView
from plain.http import Response, ResponseForbidden, ResponseRedirect
from plain.sessions.views import SessionView

from .constants import IMPERSONATE_SESSION_KEY
from .permissions import can_be_impersonator
from .requests import get_request_impersonator


class ImpersonateStartView(AuthView):
    def get(self) -> Response:
        # We *could* already be impersonating, so need to consider that
        impersonator = get_request_impersonator(self.request) or self.user
        if impersonator and can_be_impersonator(impersonator):
            self.session[IMPERSONATE_SESSION_KEY] = self.url_kwargs["id"]
            return ResponseRedirect(self.request.query_params.get("next", "/"))

        return ResponseForbidden()


class ImpersonateStopView(SessionView):
    def get(self) -> Response:
        self.session.pop(IMPERSONATE_SESSION_KEY)
        return ResponseRedirect(self.request.query_params.get("next", "/"))
