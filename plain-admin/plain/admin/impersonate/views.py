from plain.auth.views import AuthView
from plain.http import RedirectResponse, Response
from plain.sessions.views import SessionView

from .constants import _IMPERSONATE_SESSION_KEY
from .permissions import can_be_impersonator, can_impersonate_user
from .requests import get_request_impersonator


class ImpersonateStartView(AuthView):
    def get(self) -> Response:
        from app.users.models import User

        # We *could* already be impersonating, so need to consider that
        impersonator = get_request_impersonator(self.request) or self.user
        target_id = self.url_kwargs["id"]

        if not (impersonator and can_be_impersonator(impersonator)):
            return Response(status_code=403)

        # Validate that the target user exists and can be impersonated
        try:
            target_user = User.query.get(id=target_id)
        except User.DoesNotExist:
            return Response(status_code=404)

        if not can_impersonate_user(impersonator, target_user):
            return Response(status_code=403)

        self.session[_IMPERSONATE_SESSION_KEY] = target_id
        return RedirectResponse(self.request.query_params.get("next", "/"))


class ImpersonateStopView(SessionView):
    def get(self) -> Response:
        self.session.pop(_IMPERSONATE_SESSION_KEY)
        return RedirectResponse(self.request.query_params.get("next", "/"))
