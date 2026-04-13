from plain.auth.requests import get_request_user, set_request_user
from plain.http import HttpMiddleware, Request, Response
from plain.sessions import get_request_session

from .constants import _IMPERSONATE_SESSION_KEY
from .permissions import can_be_impersonator, can_impersonate_user
from .requests import set_request_impersonator


class ImpersonateMiddleware(HttpMiddleware):
    def before_request(self, request: Request) -> Response | None:
        from app.users.models import User

        session = get_request_session(request)
        user = get_request_user(request)

        if (
            session
            and _IMPERSONATE_SESSION_KEY in session
            and user
            and can_be_impersonator(user)
        ):
            try:
                user_to_impersonate = User.query.get(
                    id=session[_IMPERSONATE_SESSION_KEY]
                )
            except User.DoesNotExist:
                user_to_impersonate = None

            if user_to_impersonate:
                if not can_impersonate_user(user, user_to_impersonate):
                    # Can't impersonate this user, remove it and show an error
                    del session[_IMPERSONATE_SESSION_KEY]
                    return Response(status_code=403)

                # Finally, change the request user and keep a reference to the original
                set_request_impersonator(request, user)
                set_request_user(request, user_to_impersonate)

        return None
