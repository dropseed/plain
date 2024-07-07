from plain.auth import get_user_model
from plain.http import ResponseForbidden

from .permissions import can_be_impersonator, can_impersonate_user
from .views import IMPERSONATE_KEY


def get_user_by_pk(pk):
    UserModel = get_user_model()

    try:
        return UserModel.objects.get(pk=pk)
    except UserModel.DoesNotExist:
        return None


class ImpersonateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            IMPERSONATE_KEY in request.session
            and request.user
            and can_be_impersonator(request.user)
        ):
            user_to_impersonate = get_user_by_pk(request.session[IMPERSONATE_KEY])
            if user_to_impersonate:
                if not can_impersonate_user(request.user, user_to_impersonate):
                    # Can't impersonate this user, remove it and show an error
                    del request.session[IMPERSONATE_KEY]
                    return ResponseForbidden()

                # Finally, change the request user and keep a reference to the original
                request.impersonator = request.user
                request.user = user_to_impersonate

        return self.get_response(request)
