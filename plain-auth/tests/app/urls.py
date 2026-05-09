from plain.auth.views import AuthView, LoginRequiredView
from plain.http import Response
from plain.urls import Router, path
from plain.views import View


class LoginView(View):
    def get(self):
        return Response("login")


class ProtectedView(AuthView):
    login_required = True

    def get(self):
        return Response("protected")


class TypedUserView(LoginRequiredView):
    """Uses LoginRequiredView — `self.user` is typed as `User` (non-nullable)
    and `login_required` defaults to True. Body relies on the narrowed type
    without an `assert self.user is not None`."""

    def get(self):
        # If `self.user` were typed `User | None`, this access would need
        # an assert. LoginRequiredView narrows it.
        return Response(f"user:{self.user.username}")


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
    urls = [
        path("login/", LoginView, name="login"),
        path("protected/", ProtectedView, name="protected"),
        path("typed/", TypedUserView, name="typed"),
        path("open/", OpenView, name="open"),
        path("admin/", AdminView, name="admin"),
        path("nolink/", NoLoginUrlView, name="nolink"),
    ]
