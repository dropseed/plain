from __future__ import annotations

import hmac
from datetime import datetime
from typing import Any

from app.users.models import User

from plain.auth.sessions import login as auth_login
from plain.auth.sessions import update_session_auth_hash
from plain.auth.views import AuthView
from plain.forms import Error
from plain.html.views import TemplateView
from plain.http import (
    BadRequestError400,
    RedirectResponse,
    Response,
)
from plain.postgres.forms import create_from
from plain.signing import BadSignature, SignatureExpired, TimestampSigner
from plain.urls import reverse
from plain.utils.cache import add_never_cache_headers
from plain.utils.encoding import force_bytes

from .core import (
    authenticate,
    check_user_password,
    get_password_errors,
    send_password_reset,
    set_user_password,
)
from .forms import (
    PasswordChangeForm,
    PasswordLoginForm,
    PasswordResetForm,
    PasswordSetForm,
    PasswordSignupForm,
)


class PasswordForgotView(TemplateView):
    form_class = PasswordResetForm
    reset_confirm_url_name: str
    success_url: str = ""

    def generate_password_reset_token(self, user: Any) -> str:
        return TimestampSigner(salt="password-reset").sign_object(
            {
                "id": user.id,
                "email": user.email,
                "password": user.password,  # Hashed password
                "timestamp": datetime.now().timestamp(),  # Makes each token unique
            },
            compress=True,
        )

    def generate_password_reset_url(self, user: Any) -> str:
        token = self.generate_password_reset_token(user)
        url = reverse(self.reset_confirm_url_name) + f"?token={token}"
        return self.request.build_absolute_uri(url)

    def get(self) -> Response:
        return self.render_form(self.form_class)

    def post(self) -> Response:
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        send_password_reset(
            email=result.email, generate_reset_url=self.generate_password_reset_url
        )
        return RedirectResponse(self.success_url or "/")


class PasswordResetView(AuthView, TemplateView):
    form_class = PasswordSetForm
    reset_token_max_age = 60 * 60  # 1 hour
    success_url: str = ""
    _reset_token_session_key = "_password_reset_token"

    def check_password_reset_token(self, token: str) -> User | None:
        max_age = self.reset_token_max_age

        try:
            data = TimestampSigner(salt="password-reset").unsign_object(
                token, max_age=max_age
            )
        except SignatureExpired:
            return None
        except BadSignature:
            return None

        try:
            user = User.query.get(id=data["id"])
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return None

        # If the password has changed since the token was generated, the token is invalid.
        # (These are the hashed passwords, not the raw passwords.)
        if not hmac.compare_digest(
            force_bytes(user.password),
            force_bytes(data["password"]),
        ):
            return None

        # If the email has changed since the token was generated, the token is invalid.
        if not hmac.compare_digest(force_bytes(user.email), force_bytes(data["email"])):
            return None

        return user

    def get_user(self) -> User:
        session_token = self.session.get(self._reset_token_session_key, "")
        if not session_token:
            # No token in the session, so we can't check the password reset token.
            raise BadRequestError400("No password reset token found.")

        user = self.check_password_reset_token(session_token)
        if not user:
            # Remove it from the session if it is invalid.
            del self.session[self._reset_token_session_key]
            raise BadRequestError400("Password reset token is no longer valid.")

        return user

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(self.success_url or "/")

        # Tokens arrive as a GET parameter; stash in the session and redirect
        # to a token-free URL so the token can't leak via the Referer header.
        if token := self.request.query_params.get("token", ""):
            self.session[self._reset_token_session_key] = token
            response = RedirectResponse(self.request.path)
            add_never_cache_headers(response)
            return response

        # 400s if the reset token is missing or no longer valid.
        self.get_user()
        return self.render_form(self.form_class)

    def post(self) -> Response:
        user = self.get_user()
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        if password_errors := get_password_errors(
            user, result.new_password2, field="new_password2"
        ):
            return self.render_form(
                self.form_class,
                errors=password_errors,
                values=self.request.form_data,
            )
        set_user_password(user, result.new_password1)
        del self.session[self._reset_token_session_key]
        return RedirectResponse(self.success_url or "/")


class PasswordChangeView(AuthView, TemplateView):
    # Change to PasswordSetForm if you want to set new passwords
    # without confirming the old one.
    form_class = PasswordChangeForm
    success_url: str = ""
    login_required = True

    def get(self) -> Response:
        return self.render_form(self.form_class)

    def post(self) -> Response:
        # login_required = True guarantees an authenticated user here.
        user = self.user
        assert user is not None

        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        if not check_user_password(user, result.current_password):
            return self.render_form(
                self.form_class,
                errors=[
                    Error(
                        "Your old password was entered incorrectly. "
                        "Please enter it again.",
                        code="incorrect_password",
                        field="current_password",
                    )
                ],
                values=self.request.form_data,
            )
        if password_errors := get_password_errors(
            user, result.new_password2, field="new_password2"
        ):
            return self.render_form(
                self.form_class,
                errors=password_errors,
                values=self.request.form_data,
            )
        set_user_password(user, result.new_password1)
        # Updating the password logs out all other sessions for the user
        # except the current one.
        update_session_auth_hash(self.request, user)
        return RedirectResponse(self.success_url or "/")


class PasswordLoginView(AuthView, TemplateView):
    form_class = PasswordLoginForm
    success_url = "/"

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(self.success_url)
        return self.render_form(self.form_class)

    def post(self) -> Response:
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        user = authenticate(email=result.email, password=result.password)
        if user is None:
            return self.render_form(
                self.form_class,
                errors=[
                    Error(
                        "Please enter a correct email and password. Note "
                        "that both fields may be case-sensitive.",
                        code="invalid_login",
                    )
                ],
                values=self.request.form_data,
            )
        auth_login(self.request, user)
        return RedirectResponse(self.success_url)


class PasswordSignupView(TemplateView):
    form_class = PasswordSignupForm
    success_url = "/"

    def get(self) -> Response:
        return self.render_form(self.form_class)

    def post(self) -> Response:
        result = self.validate_form(self.form_class)
        if isinstance(result, Response):
            return result
        create_from(User, result)
        # To sign the new user in immediately, capture create_from()'s
        # return value and pass it to auth_login(self.request, user).
        return RedirectResponse(self.success_url)
