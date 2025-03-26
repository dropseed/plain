from plain.auth import get_user_model
from plain.auth.sessions import login as auth_login
from plain.auth.sessions import update_session_auth_hash
from plain.exceptions import ValidationError
from plain.http import (
    ResponseRedirect,
)
from plain.utils.cache import add_never_cache_headers
from plain.views import CreateView, FormView

from .forms import (
    PasswordChangeForm,
    PasswordLoginForm,
    PasswordResetForm,
    PasswordSetForm,
    PasswordSignupForm,
)
from .tokens import default_token_generator
from .utils import urlsafe_base64_decode


class PasswordResetView(FormView):
    form_class = PasswordResetForm
    reset_token_generator = default_token_generator
    reset_confirm_url_name: str

    def form_valid(self, form):
        form.save(
            request=self.request,
            reset_confirm_url_name=self.reset_confirm_url_name,
            token_generator=self.reset_token_generator,
        )
        return super().form_valid(form)


class PasswordResetConfirmView(FormView):
    form_class = PasswordSetForm
    reset_url_token = "set-password"
    reset_token_generator = default_token_generator
    _reset_token_session_key = "_password_reset_token"

    def get_response(self):
        self.validlink = False
        self.user = self.get_user(self.url_kwargs["uidb64"])

        if not self.user:
            # Display the "Password reset unsuccessful" page.
            response = self.render_to_response(self.get_template_context())
            add_never_cache_headers(response)
            return response

        token = self.url_kwargs["token"]
        if token == self.reset_url_token:
            session_token = self.request.session.get(self._reset_token_session_key)
            if self.reset_token_generator.check_token(self.user, session_token):
                # If the token is valid, display the password reset form.
                self.validlink = True
                response = super().get_response()
                add_never_cache_headers(response)
                return response
        else:
            if self.reset_token_generator.check_token(self.user, token):
                # Store the token in the session and redirect to the
                # password reset form at a URL without the token. That
                # avoids the possibility of leaking the token in the
                # HTTP Referer header.
                self.request.session[self._reset_token_session_key] = token
                redirect_url = self.request.path.replace(token, self.reset_url_token)
                response = ResponseRedirect(redirect_url)
                add_never_cache_headers(response)
                return response

    def get_user(self, uidb64):
        UserModel = get_user_model()
        try:
            # urlsafe_base64_decode() decodes to bytestring
            uid = urlsafe_base64_decode(uidb64).decode()
            user = UserModel._default_manager.get(pk=uid)
        except (
            TypeError,
            ValueError,
            OverflowError,
            UserModel.DoesNotExist,
            ValidationError,
        ):
            user = None
        return user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.user
        return kwargs

    def form_valid(self, form):
        form.save()
        del self.request.session[self._reset_token_session_key]
        # if self.post_reset_login:
        #     auth_login(self.request, user, self.post_reset_login_backend)
        return super().form_valid(form)

    def get_template_context(self):
        context = super().get_template_context()
        if self.validlink:
            context["validlink"] = True
        else:
            context.update(
                {
                    "form": None,
                    "title": "Password reset unsuccessful",
                    "validlink": False,
                }
            )
        return context


class PasswordChangeView(FormView):
    # Change to PasswordSetForm if you want to set new passwords
    # without confirming the old one.
    form_class = PasswordChangeForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.save()
        # Updating the password logs out all other sessions for the user
        # except the current one.
        update_session_auth_hash(self.request, form.user)
        return super().form_valid(form)


class PasswordLoginView(FormView):
    form_class = PasswordLoginForm
    success_url = "/"

    def get(self):
        # Redirect if the user is already logged in
        if self.request.user:
            return ResponseRedirect(self.success_url)

        return super().get()

    def form_valid(self, form):
        # Log the user in and redirect
        auth_login(self.request, form.get_user())

        return super().form_valid(form)


class PasswordSignupView(CreateView):
    form_class = PasswordSignupForm
    success_url = "/"

    def form_valid(self, form):
        # # Log the user in and redirect
        # auth_login(self.request, form.save())

        return super().form_valid(form)
