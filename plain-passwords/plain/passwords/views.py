from __future__ import annotations

import hmac
from datetime import datetime
from typing import TYPE_CHECKING, Any

from plain.auth.sessions import login as auth_login
from plain.auth.sessions import update_session_auth_hash
from plain.auth.views import AuthView
from plain.http import (
    BadRequestError400,
    RedirectResponse,
)
from plain.schema import BoundSchema, Invalid
from plain.signing import BadSignature, SignatureExpired, TimestampSigner
from plain.urls import reverse
from plain.utils.cache import add_never_cache_headers
from plain.utils.encoding import force_bytes
from plain.views import SchemaCreateView, SchemaView

from app.users.models import User

from .forms import (
    PasswordChangeSchema,
    PasswordLoginSchema,
    PasswordResetSchema,
    PasswordSetSchema,
    PasswordSignupSchema,
    authenticate,
)

if TYPE_CHECKING:
    from plain.http import Response


class PasswordForgotView(SchemaView[PasswordResetSchema]):
    schema_class = PasswordResetSchema
    reset_confirm_url_name: str

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

    def schema_valid(self, result: PasswordResetSchema) -> Response:
        result.save(generate_reset_url=self.generate_password_reset_url)
        return super().schema_valid(result)


class PasswordResetView(AuthView, SchemaView[PasswordSetSchema]):
    schema_class = PasswordSetSchema
    reset_token_max_age = 60 * 60  # 1 hour
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

    def get(self) -> Response:
        if self.user:
            # Redirect if the user is already logged in
            return RedirectResponse(str(self.success_url) if self.success_url else "/")

        # Tokens are initially passed as GET parameters and we
        # immediately store them in the session and remove it from the URL.
        if token := self.request.query_params.get("token", ""):
            # Store the token in the session and redirect to the
            # password reset form at a URL without the token. That
            # avoids the possibility of leaking the token in the
            # HTTP Referer header.
            self.session[self._reset_token_session_key] = token
            # Redirect to the path itself, without the GET parameters
            response = RedirectResponse(self.request.path)
            add_never_cache_headers(response)
            return response

        return super().get()

    def get_user(self) -> User:
        session_token = self.session.get(self._reset_token_session_key, "")
        if not session_token:
            raise BadRequestError400("No password reset token found.")

        user = self.check_password_reset_token(session_token)
        if not user:
            del self.session[self._reset_token_session_key]
            raise BadRequestError400("Password reset token is no longer valid.")

        return user

    def post(self) -> Response:
        # Pass the user via context so the schema can validate the new
        # password against the user's model field validators.
        user = self.get_user()
        result = self.schema_class.validate(
            self.request.form_data,
            files=self.request.files,
            context={"user": user},
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(self.schema_class, result)
            return self.schema_invalid(bound)
        return self.schema_valid_with_user(result, user)

    def schema_valid_with_user(self, result: PasswordSetSchema, user: User) -> Response:
        result.save(user=user)
        del self.session[self._reset_token_session_key]
        return RedirectResponse(self.get_success_url(result))


class PasswordChangeView(AuthView, SchemaView[PasswordChangeSchema]):
    schema_class = PasswordChangeSchema
    login_required = True

    def post(self) -> Response:
        # `self.user` is guaranteed by login_required=True; assert for ty.
        assert self.user is not None
        result = self.schema_class.validate(
            self.request.form_data,
            files=self.request.files,
            context={"user": self.user},
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(self.schema_class, result)
            return self.schema_invalid(bound)
        # Already validated against self.user via context.
        result.save(user=self.user)
        # Updating the password logs out all other sessions for the user
        # except the current one.
        update_session_auth_hash(self.request, self.user)
        return RedirectResponse(self.get_success_url(result))


class PasswordLoginView(AuthView, SchemaView[PasswordLoginSchema]):
    schema_class = PasswordLoginSchema
    success_url = "/"

    def get(self) -> Response:
        # Redirect if the user is already logged in
        if self.user:
            return RedirectResponse(self.success_url)

        return super().get()

    def schema_valid(self, result: PasswordLoginSchema) -> Response:
        # Authentication happens here, not in the schema — the schema
        # validates email/password format only.
        user = authenticate(result.email, result.password)
        if user is None:
            bound = BoundSchema.from_invalid(
                self.schema_class,
                Invalid(
                    errors={
                        "__all__": [
                            "Please enter a correct email and password. "
                            "Note that both fields may be case-sensitive."
                        ]
                    },
                    raw=dict(self.request.form_data),
                ),
            )
            return self.schema_invalid(bound)

        auth_login(self.request, user)
        return super().schema_valid(result)


class PasswordSignupView(SchemaCreateView[PasswordSignupSchema]):
    """Create a new User from a signup form. The schema's `save()` returns
    the User instance; SchemaCreateView stashes it on `self.object` so the
    redirect URL can use the new id."""

    schema_class = PasswordSignupSchema
    success_url = "/"

    # # Log the user in and redirect
    # def schema_valid(self, result):
    #     auth_login(self.request, self.object)
    #     return super().schema_valid(result)
