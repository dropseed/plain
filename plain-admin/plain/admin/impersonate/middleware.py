from typing import Any

from plain.auth import get_user_model
from plain.auth.requests import get_request_user, set_request_user
from plain.http import HttpMiddleware, Request, Response
from plain.sessions import get_request_session

from .constants import _IMPERSONATE_SESSION_KEY
from .permissions import can_be_impersonator, can_impersonate_user
from .requests import set_request_impersonator


def get_user_by_id(id: int) -> Any | None:
    UserModel = get_user_model()

    try:
        return UserModel.query.get(id=id)
    except UserModel.DoesNotExist:
        return None


class ImpersonateMiddleware(HttpMiddleware):
    def process_request(self, request: Request) -> Response:
        session = get_request_session(request)
        user = get_request_user(request)

        if (
            session
            and _IMPERSONATE_SESSION_KEY in session
            and user
            and can_be_impersonator(user)
        ):
            user_to_impersonate = get_user_by_id(session[_IMPERSONATE_SESSION_KEY])
            if user_to_impersonate:
                if not can_impersonate_user(user, user_to_impersonate):
                    # Can't impersonate this user, remove it and show an error
                    del session[_IMPERSONATE_SESSION_KEY]
                    return Response(status_code=403)

                # Finally, change the request user and keep a reference to the original
                set_request_impersonator(request, user)
                set_request_user(request, user_to_impersonate)

        return self.get_response(request)
