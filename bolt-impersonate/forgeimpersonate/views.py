from django.http import HttpResponseForbidden, HttpResponseRedirect
from django.views import View

from .permissions import can_be_impersonator

IMPERSONATE_KEY = "impersonate"


class ImpersonateStartView(View):
    def get(self, request, *args, **kwargs):
        # We *could* already be impersonating, so need to consider that
        impersonator = getattr(request, "impersonator", request.user)
        if impersonator and can_be_impersonator(impersonator):
            request.session[IMPERSONATE_KEY] = kwargs["pk"]
            return HttpResponseRedirect(request.GET.get("next", "/"))

        return HttpResponseForbidden()


class ImpersonateStopView(View):
    def get(self, request, *args, **kwargs):
        request.session.pop(IMPERSONATE_KEY)
        return HttpResponseRedirect(request.GET.get("next", "/"))
