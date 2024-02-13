from bolt.csrf.middleware import rotate_token
from bolt.exceptions import ImproperlyConfigured
from bolt.packages import packages as bolt_packages
from bolt.runtime import settings
from bolt.utils.crypto import constant_time_compare

from .signals import user_logged_in, user_logged_out

USER_ID_SESSION_KEY = "_auth_user_id"
USER_HASH_SESSION_KEY = "_auth_user_hash"


def _get_user_id_from_session(request):
    # This value in the session is always serialized to a string, so we need
    # to convert it back to Python whenever we access it.
    return get_user_model()._meta.pk.to_python(request.session[USER_ID_SESSION_KEY])


def login(request, user):
    """
    Persist a user id and a backend in the request. This way a user doesn't
    have to reauthenticate on every request. Note that data set during
    the anonymous session is retained when the user logs in.
    """
    if user.SESSION_HASH_FIELD:
        session_auth_hash = user.get_session_auth_hash()
    else:
        session_auth_hash = ""

    if USER_ID_SESSION_KEY in request.session:
        if _get_user_id_from_session(request) != user.pk:
            # To avoid reusing another user's session, create a new, empty
            # session if the existing session corresponds to a different
            # authenticated user.
            request.session.flush()
        elif session_auth_hash and not constant_time_compare(
            request.session.get(USER_HASH_SESSION_KEY, ""), session_auth_hash
        ):
            # If the session hash does not match the current hash, reset the
            # session. Most likely this means the password was changed.
            request.session.flush()
    else:
        request.session.cycle_key()

    request.session[USER_ID_SESSION_KEY] = user._meta.pk.value_to_string(user)
    request.session[USER_HASH_SESSION_KEY] = session_auth_hash
    if hasattr(request, "user"):
        request.user = user
    rotate_token(request)
    user_logged_in.send(sender=user.__class__, request=request, user=user)


def logout(request):
    """
    Remove the authenticated user's ID from the request and flush their session
    data.
    """
    # Dispatch the signal before the user is logged out so the receivers have a
    # chance to find out *who* logged out.
    user = getattr(request, "user", None)
    user_logged_out.send(sender=user.__class__, request=request, user=user)
    request.session.flush()
    if hasattr(request, "user"):
        request.user = None


def get_user_model():
    """
    Return the User model that is active in this project.
    """
    try:
        return bolt_packages.get_model(settings.AUTH_USER_MODEL, require_ready=False)
    except ValueError:
        raise ImproperlyConfigured(
            "AUTH_USER_MODEL must be of the form 'package_label.model_name'"
        )
    except LookupError:
        raise ImproperlyConfigured(
            "AUTH_USER_MODEL refers to model '%s' that has not been installed"
            % settings.AUTH_USER_MODEL
        )


def get_user(request):
    """
    Return the user model instance associated with the given request session.
    If no user is retrieved, return None.
    """
    if USER_ID_SESSION_KEY not in request.session:
        return None

    user_id = _get_user_id_from_session(request)

    UserModel = get_user_model()
    try:
        user = UserModel._default_manager.get(pk=user_id)
    except UserModel.DoesNotExist:
        return None

    # If the user models defines a specific field to also hash and compare
    # (like password), then we verify that the hash of that field is still
    # the same as when the session was created.
    #
    # If it has changed (i.e. password changed), then the session
    # is no longer valid and cleared out.
    if user.SESSION_HASH_FIELD:
        session_hash = request.session.get(USER_HASH_SESSION_KEY)
        if not session_hash:
            session_hash_verified = False
        else:
            session_auth_hash = user.get_session_auth_hash()
            session_hash_verified = constant_time_compare(
                session_hash, session_auth_hash
            )
        if not session_hash_verified:
            # If the current secret does not verify the session, try
            # with the fallback secrets and stop when a matching one is
            # found.
            if session_hash and any(
                constant_time_compare(session_hash, fallback_auth_hash)
                for fallback_auth_hash in user.get_session_auth_fallback_hash()
            ):
                request.session.cycle_key()
                request.session[USER_HASH_SESSION_KEY] = session_auth_hash
            else:
                request.session.flush()
                user = None

    return user
