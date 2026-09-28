from app.users.models import User
from plain.auth import login, logout
from plain.auth.sessions import _USER_ID_SESSION_KEY
from plain.auth.views import AuthView
from plain.http import Response
from plain.sessions import get_request_session
from plain.urls import Router, path
from plain.views import View


class LoginView(View):
    def get(self):
        return Response("login")


class VisitView(View):
    """Write to the anonymous session so a session cookie is issued."""

    def get(self):
        get_request_session(self.request)["visited"] = "yes"
        return Response("visited")


class SessionLoginView(View):
    """Log a user in through the real ``login()`` flow."""

    def post(self):
        user = User.query.get(id=self.request.form_data["user_id"])
        login(self.request, user)
        return Response("logged in")


class LegacySessionIdView(View):
    """Log in, then rewrite the stored id the way an older release wrote it.

    `login()` stores `user.id`, an int. Sessions written when it was stored
    as a string are still out there, and they have to keep resolving.
    """

    def post(self):
        user = User.query.get(id=self.request.form_data["user_id"])
        login(self.request, user)
        session = get_request_session(self.request)
        session[_USER_ID_SESSION_KEY] = self.request.form_data["stored_id"]
        return Response("logged in")


class SessionLogoutView(View):
    """Log the current user out through the real ``logout()`` flow."""

    def post(self):
        logout(self.request)
        return Response("logged out")


class WhoView(AuthView):
    login_required = True

    def get(self):
        # login_required guarantees an authenticated user here.
        return Response(self.user.username)  # ty: ignore[unresolved-attribute]


class ProtectedView(AuthView):
    login_required = True

    def get(self):
        return Response("protected")


class OpenView(AuthView):
    # login_required = False

    def get(self):
        return Response("open")


class AdminView(AuthView):
    admin_required = True

    def get(self):
        return Response("admin")


class NoLoginUrlView(AuthView):
    login_required = True
    login_url = None

    def get(self):
        return Response("none")


class AppRouter(Router):
    namespace = ""
    urls = (
        path("login", LoginView, name="login"),
        path("visit", VisitView, name="visit"),
        path("session-login", SessionLoginView, name="session_login"),
        path("legacy-session-id", LegacySessionIdView, name="legacy_session_id"),
        path("session-logout", SessionLogoutView, name="session_logout"),
        path("whoami", WhoView, name="whoami"),
        path("protected", ProtectedView, name="protected"),
        path("open", OpenView, name="open"),
        path("admin", AdminView, name="admin"),
        path("nolink", NoLoginUrlView, name="nolink"),
    )
