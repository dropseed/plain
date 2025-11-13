from __future__ import annotations

import hmac
from datetime import datetime
from typing import TYPE_CHECKING, Any

from plain import signing
from plain.auth import get_user_model
from plain.auth.sessions import login as auth_login
from plain.auth.sessions import update_session_auth_hash
from plain.auth.views import AuthViewMixin
from plain.exceptions import BadRequest
from plain.forms import BaseForm
from plain.http import (
    ResponseRedirect,
)
from plain.urls import reverse
from plain.utils.cache import add_never_cache_headers
from plain.utils.encoding import force_bytes
from plain.views import CreateView, FormView

from .forms import (
    PasswordChangeForm,
    PasswordLoginForm,
    PasswordResetForm,
    PasswordSetForm,
    PasswordSignupForm,
)

if TYPE_CHECKING:
    from plain.http import Response
    from plain.models import Model


class PasswordForgotView(FormView):
    form_class = PasswordResetForm
    reset_confirm_url_name: str

    def generate_password_reset_token(self, user: Any) -> str:
        return signing.dumps(
            {
                "id": user.id,
                "email": user.email,
                "password": user.password,  # Hashed password
                "timestamp": datetime.now().timestamp(),  # Makes each token unique
            },
            salt="password-reset",
            compress=True,
        )

    def generate_password_reset_url(self, user: Any) -> str:
        token = self.generate_password_reset_token(user)
        url = reverse(self.reset_confirm_url_name) + f"?token={token}"
        return self.request.build_absolute_uri(url)

    def form_valid(self, form: PasswordResetForm) -> Response:
        form.save(
            generate_reset_url=self.generate_password_reset_url,
        )
        return super().form_valid(form)


class PasswordResetView(AuthViewMixin, FormView):
    form_class = PasswordSetForm
    reset_token_max_age = 60 * 60  # 1 hour
    _reset_token_session_key = "_password_reset_token"

    def check_password_reset_token(self, token: str) -> Model | None:
        max_age = self.reset_token_max_age

        try:
            data = signing.loads(token, salt="password-reset", max_age=max_age)
        except signing.SignatureExpired:
            return None
        except signing.BadSignature:
            return None

        UserModel = get_user_model()
        try:
            user = UserModel.query.get(id=data["id"])
        except (TypeError, ValueError, OverflowError, UserModel.DoesNotExist):
            return None

        # If the password has changed since the token was generated, the token is invalid.
        # (These are the hashed passwords, not the raw passwords.)
        if not hmac.compare_digest(
            force_bytes(user.password), force_bytes(data["password"])
        ):
            return None

        # If the email has changed since the token was generated, the token is invalid.
        if not hmac.compare_digest(force_bytes(user.email), force_bytes(data["email"])):
            return None

        return user

    def get(self) -> Response:
        if self.user:
            # Redirect if the user is already logged in
            return ResponseRedirect(str(self.success_url) if self.success_url else "/")

        # Tokens are initially passed as GET parameters and we
        # immediately store them in the session and remove it from the URL.
        if token := self.request.query_params.get("token", ""):
            # Store the token in the session and redirect to the
            # password reset form at a URL without the token. That
            # avoids the possibility of leaking the token in the
            # HTTP Referer header.
            self.session[self._reset_token_session_key] = token
            # Redirect to the path itself, without the GET parameters
            response = ResponseRedirect(self.request.path)
            add_never_cache_headers(response)
            return response

        return super().get()

    def get_user(self) -> Model:
        session_token = self.session.get(self._reset_token_session_key, "")
        if not session_token:
            # No token in the session, so we can't check the password reset token.
            raise BadRequest("No password reset token found.")

        user = self.check_password_reset_token(session_token)
        if not user:
            # Remove it from the session if it is invalid.
            del self.session[self._reset_token_session_key]
            raise BadRequest("Password reset token is no longer valid.")

        return user

    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.get_user()
        return kwargs

    def form_valid(self, form: PasswordSetForm) -> Response:
        form.save()
        del self.session[self._reset_token_session_key]
        # If you wanted, you could log in the user here so they don't have to
        # go through the log in form again.
        return super().form_valid(form)


class PasswordChangeView(AuthViewMixin, FormView):
    # Change to PasswordSetForm if you want to set new passwords
    # without confirming the old one.
    form_class = PasswordChangeForm

    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.user
        return kwargs

    def form_valid(self, form: PasswordChangeForm) -> Response:
        form.save()
        # Updating the password logs out all other sessions for the user
        # except the current one.
        update_session_auth_hash(self.request, form.user)
        return super().form_valid(form)


class PasswordLoginView(AuthViewMixin, FormView):
    form_class = PasswordLoginForm
    success_url = "/"

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return ResponseRedirect(self.success_url)

        return super().get()

    def form_valid(self, form: PasswordLoginForm) -> Response:
        # Log the user in and redirect
        auth_login(self.request, form.get_user())

        return super().form_valid(form)


class PasswordSignupView(CreateView):
    form_class = PasswordSignupForm
    success_url = "/"

    def form_valid(self, form: BaseForm) -> Response:
        # # Log the user in and redirect
        # auth_login(self.request, form.save())

        return super().form_valid(form)
