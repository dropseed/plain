from plain.auth import get_user_model
from plain.signing import BadSignature, SignatureExpired
from plain.urls import reverse

from . import signing


class LoginLinkExpired(Exception):
    pass


class LoginLinkInvalid(Exception):
    pass


class LoginLinkChanged(Exception):
    pass


def generate_link_url(*, request, user, email, expires_in):
    """
    Generate a login link using both the user's ID
    and email address, so links break if the user email changes or is assigned to another user.
    """
    token = signing.dumps({"user_id": user.id, "email": email}, expires_in=expires_in)

    return request.build_absolute_uri(reverse("loginlink:login", token))


def get_link_token_user(token):
    """
    Validate a link token and get the user from it.
    """
    try:
        signed_data = signing.loads(token)
    except SignatureExpired:
        raise LoginLinkExpired()
    except BadSignature:
        raise LoginLinkInvalid()

    user_model = get_user_model()
    user_id = signed_data["user_id"]
    email = signed_data["email"]

    try:
        return user_model.objects.get(id=user_id, email__iexact=email)
    except user_model.DoesNotExist:
        raise LoginLinkChanged()
