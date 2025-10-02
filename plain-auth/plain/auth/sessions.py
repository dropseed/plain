import hmac

from plain.exceptions import ImproperlyConfigured
from plain.models import models_registry
from plain.runtime import settings
from plain.sessions import get_request_session
from plain.utils.crypto import salted_hmac
from plain.utils.encoding import force_bytes

from .requests import get_request_user, set_request_user

USER_ID_SESSION_KEY = "_auth_user_id"
USER_HASH_SESSION_KEY = "_auth_user_hash"


def get_session_auth_hash(user):
    """
    Return an HMAC of the password field.
    """
    return _get_session_auth_hash(user)


def update_session_auth_hash(request, user):
    """
    Updating a user's password (for example) logs out all sessions for the user.

    Take the current request and the updated user object from which the new
    session hash will be derived and update the session hash appropriately to
    prevent a password change from logging out the session from which the
    password was changed.
    """

    session = get_request_session(request)
    session.cycle_key()
    if get_request_user(request) == user:
        session[USER_HASH_SESSION_KEY] = get_session_auth_hash(user)


def get_session_auth_fallback_hash(user):
    for fallback_secret in settings.SECRET_KEY_FALLBACKS:
        yield _get_session_auth_hash(user, secret=fallback_secret)


def _get_session_auth_hash(user, secret=None):
    key_salt = "plain.auth.get_session_auth_hash"
    return salted_hmac(
        key_salt,
        getattr(user, settings.AUTH_USER_SESSION_HASH_FIELD),
        secret=secret,
        algorithm="sha256",
    ).hexdigest()


def login(request, user):
    """
    Persist a user id and a backend in the request. This way a user doesn't
    have to reauthenticate on every request. Note that data set during
    the anonymous session is retained when the user logs in.
    """
    session = get_request_session(request)

    if settings.AUTH_USER_SESSION_HASH_FIELD:
        session_auth_hash = get_session_auth_hash(user)
    else:
        session_auth_hash = ""

    if USER_ID_SESSION_KEY in session:
        if int(session[USER_ID_SESSION_KEY]) != user.id:
            # To avoid reusing another user's session, create a new, empty
            # session if the existing session corresponds to a different
            # authenticated user.
            session.flush()
        elif session_auth_hash and not hmac.compare_digest(
            force_bytes(session.get(USER_HASH_SESSION_KEY, "")),
            force_bytes(session_auth_hash),
        ):
            # If the session hash does not match the current hash, reset the
            # session. Most likely this means the password was changed.
            session.flush()
    else:
        # Invalidate the current session key and generate a new one to enhance security,
        # typically done after user login to prevent session fixation attacks.
        session.cycle_key()

    session[USER_ID_SESSION_KEY] = user.id
    session[USER_HASH_SESSION_KEY] = session_auth_hash
    set_request_user(request, user)


def logout(request):
    """
    Remove the authenticated user's ID from the request and flush their session
    data.
    """
    # Dispatch the signal before the user is logged out so the receivers have a
    # chance to find out *who* logged out.
    session = get_request_session(request)
    session.flush()
    set_request_user(request, None)


def get_user_model():
    """
    Return the User model that is active in this project.
    """
    try:
        return models_registry.get_model(settings.AUTH_USER_MODEL, require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(
            "AUTH_USER_MODEL must be of the form 'package_label.model_name'"
        )
    except LookupError:
        raise ImproperlyConfigured(
            f"AUTH_USER_MODEL refers to model '{settings.AUTH_USER_MODEL}' that has not been installed"
        )


def get_user(request):
    """
    Return the user model instance associated with the given request session.
    If no user is retrieved, return None.
    """
    session = get_request_session(request)

    if USER_ID_SESSION_KEY not in session:
        return None

    UserModel = get_user_model()
    try:
        user = UserModel.query.get(id=session[USER_ID_SESSION_KEY])
    except UserModel.DoesNotExist:
        return None

    # If the user models defines a specific field to also hash and compare
    # (like password), then we verify that the hash of that field is still
    # the same as when the session was created.
    #
    # If it has changed (i.e. password changed), then the session
    # is no longer valid and cleared out.
    if settings.AUTH_USER_SESSION_HASH_FIELD:
        session_hash = session.get(USER_HASH_SESSION_KEY)
        if not session_hash:
            session_hash_verified = False
        else:
            session_auth_hash = get_session_auth_hash(user)
            session_hash_verified = hmac.compare_digest(
                force_bytes(session_hash), force_bytes(session_auth_hash)
            )
        if not session_hash_verified:
            # If the current secret does not verify the session, try
            # with the fallback secrets and stop when a matching one is
            # found.
            if session_hash and any(
                hmac.compare_digest(
                    force_bytes(session_hash), force_bytes(fallback_auth_hash)
                )
                for fallback_auth_hash in get_session_auth_fallback_hash(user)
            ):
                session.cycle_key()
                session[USER_HASH_SESSION_KEY] = session_auth_hash
            else:
                session.flush()
                user = None

    return user
