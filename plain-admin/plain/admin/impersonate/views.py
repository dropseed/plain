from plain.http import ResponseForbidden, ResponseRedirect
from plain.views import View

from .permissions import can_be_impersonator

IMPERSONATE_KEY = "impersonate"


class ImpersonateStartView(View):
    def get(self):
        # We *could* already be impersonating, so need to consider that
        impersonator = getattr(self.request, "impersonator", self.request.user)
        if impersonator and can_be_impersonator(impersonator):
            self.request.session[IMPERSONATE_KEY] = self.url_kwargs["pk"]
            return ResponseRedirect(self.request.query_params.get("next", "/"))

        return ResponseForbidden()


class ImpersonateStopView(View):
    def get(self):
        self.request.session.pop(IMPERSONATE_KEY)
        return ResponseRedirect(self.request.query_params.get("next", "/"))
