from bolt.http import HttpResponseForbidden, HttpResponseRedirect
from bolt.views import View

from .permissions import can_be_impersonator

IMPERSONATE_KEY = "impersonate"


class ImpersonateStartView(View):
    def get(self):
        # We *could* already be impersonating, so need to consider that
        impersonator = getattr(self.request, "impersonator", self.request.user)
        if impersonator and can_be_impersonator(impersonator):
            self.request.session[IMPERSONATE_KEY] = self.url_kwargs["pk"]
            return HttpResponseRedirect(self.request.GET.get("next", "/"))

        return HttpResponseForbidden()


class ImpersonateStopView(View):
    def get(self):
        self.request.session.pop(IMPERSONATE_KEY)
        return HttpResponseRedirect(self.request.GET.get("next", "/"))
