from urllib.parse import urlparse, urlunparse

# Avoid shadowing the login() and logout() views below.
from bolt.auth import REDIRECT_FIELD_NAME, get_user_model, update_session_auth_hash
from bolt.auth import login as auth_login
from bolt.auth import logout as auth_logout
from bolt.auth.forms import (
    AuthenticationForm,
    PasswordChangeForm,
    PasswordResetForm,
    SetPasswordForm,
)
from bolt.auth.tokens import default_token_generator
from bolt.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from bolt.http import HttpResponse, HttpResponseRedirect, QueryDict
from bolt.runtime import settings
from bolt.urls import reverse, reverse_lazy
from bolt.utils.cache import add_never_cache_headers
from bolt.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode
from bolt.views import FormView, TemplateView

from .utils import resolve_url


class LoginRequired(Exception):
    def __init__(self, login_url=None, redirect_field_name="next"):
        self.login_url = login_url or settings.LOGIN_URL
        self.redirect_field_name = redirect_field_name


class AuthViewMixin:
    login_required = True
    staff_required = False
    login_url = None

    def check_auth(self) -> None:
        """
        Raises either LoginRequired or PermissionDenied.
        - LoginRequired can specify a login_url and redirect_field_name
        - PermissionDenied can specify a message
        """

        if not hasattr(self, "request"):
            raise AttributeError(
                "AuthViewMixin requires the request attribute to be set."
            )

        if self.login_required and not self.request.user:
            raise LoginRequired(login_url=self.login_url)

        if self.staff_required and not self.request.user.is_staff:
            # Ideally could customize staff_required_status_code,
            # but we can't set status code with an exception...
            # (404 to hide a private url from non-staff)
            raise PermissionDenied

    def get_response(self) -> HttpResponse:
        if not hasattr(self, "request"):
            raise AttributeError(
                "AuthViewMixin requires the request attribute to be set."
            )

        try:
            self.check_auth()
        except LoginRequired as e:
            from bolt.auth.views import (
                redirect_to_login,
            )

            # Ideally this could be handled elsewhere... like PermissionDenied
            # also seems like this code is used multiple places anyway...
            # could be easier to get redirect query param
            path = self.request.build_absolute_uri()
            resolved_login_url = reverse(e.login_url)
            # If the login url is the same scheme and net location then use the
            # path as the "next" url.
            login_scheme, login_netloc = urlparse(resolved_login_url)[:2]
            current_scheme, current_netloc = urlparse(path)[:2]
            if (not login_scheme or login_scheme == current_scheme) and (
                not login_netloc or login_netloc == current_netloc
            ):
                path = self.request.get_full_path()
            return redirect_to_login(
                path,
                resolved_login_url,
                e.redirect_field_name,
            )

        return super().get_response()  # type: ignore


class RedirectURLMixin:
    next_page = None
    redirect_field_name = REDIRECT_FIELD_NAME
    success_url_allowed_hosts = set()

    def get_success_url(self):
        return self.get_redirect_url() or self.get_default_redirect_url()

    def get_redirect_url(self):
        """Return the user-originating redirect URL if it's safe."""
        redirect_to = self.request.POST.get(
            self.redirect_field_name, self.request.GET.get(self.redirect_field_name)
        )
        url_is_safe = url_has_allowed_host_and_scheme(
            url=redirect_to,
            allowed_hosts=self.get_success_url_allowed_hosts(),
            require_https=self.request.is_secure(),
        )
        return redirect_to if url_is_safe else ""

    def get_success_url_allowed_hosts(self):
        return {self.request.get_host(), *self.success_url_allowed_hosts}

    def get_default_redirect_url(self):
        """Return the default redirect URL."""
        if self.next_page:
            return resolve_url(self.next_page)
        raise ImproperlyConfigured("No URL to redirect to. Provide a next_page.")


class LoginView(RedirectURLMixin, FormView):
    """
    Display the login form and handle the login action.
    """

    form_class = AuthenticationForm
    template_name = "auth/login.html"

    def get_response(self):
        if self.request.user:
            redirect_to = self.get_success_url()
            if redirect_to == self.request.path:
                raise ValueError(
                    "Redirection loop for authenticated user detected. Check that "
                    "your LOGIN_REDIRECT_URL doesn't point to a login page."
                )
            return HttpResponseRedirect(redirect_to)
        response = super().get_response()
        add_never_cache_headers(response)
        return response

    def get_default_redirect_url(self):
        """Return the default redirect URL."""
        if self.next_page:
            return resolve_url(self.next_page)
        else:
            return resolve_url(settings.LOGIN_REDIRECT_URL)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        """Security check complete. Log the user in."""
        auth_login(self.request, form.get_user())
        return HttpResponseRedirect(self.get_success_url())

    def get_template_context(self):
        context = super().get_template_context()
        context[self.redirect_field_name] = self.get_redirect_url()
        return context


class LogoutView(RedirectURLMixin, TemplateView):
    """
    Log out the user and display the 'You are logged out' message.
    """

    http_method_names = ["post", "options"]
    template_name = "auth/logged_out.html"
    extra_context = None

    def get_response(self):
        response = super().get_response()
        add_never_cache_headers(response)
        return response

    def post(self):
        """Logout may be done via POST."""
        auth_logout(self.request)
        redirect_to = self.get_success_url()
        if redirect_to != self.request.get_full_path():
            # Redirect to target page once the session has been cleared.
            return HttpResponseRedirect(redirect_to)
        return super().get()

    def get_default_redirect_url(self):
        """Return the default redirect URL."""
        if self.next_page:
            return resolve_url(self.next_page)
        elif settings.LOGOUT_REDIRECT_URL:
            return resolve_url(settings.LOGOUT_REDIRECT_URL)
        else:
            return self.request.path

    def get_template_context(self):
        context = super().get_template_context()
        context.update(
            {
                "title": "Logged out",
                "subtitle": None,
                **(self.extra_context or {}),
            }
        )
        return context


def redirect_to_login(next, login_url=None, redirect_field_name=REDIRECT_FIELD_NAME):
    """
    Redirect the user to the login page, passing the given 'next' page.
    """
    resolved_url = resolve_url(login_url or settings.LOGIN_URL)

    login_url_parts = list(urlparse(resolved_url))
    if redirect_field_name:
        querystring = QueryDict(login_url_parts[4], mutable=True)
        querystring[redirect_field_name] = next
        login_url_parts[4] = querystring.urlencode(safe="/")

    return HttpResponseRedirect(urlunparse(login_url_parts))


# Class-based password reset views
# - PasswordResetView sends the mail
# - PasswordResetDoneView shows a success message for the above
# - PasswordResetConfirmView checks the link the user clicked and
#   prompts for a new password
# - PasswordResetCompleteView shows a success message for the above


class PasswordContextMixin:
    extra_context = None

    def get_template_context(self):
        context = super().get_template_context()
        context.update(
            {"title": self.title, "subtitle": None, **(self.extra_context or {})}
        )
        return context


class PasswordResetView(PasswordContextMixin, FormView):
    email_template_name = "auth/password_reset_email.html"
    extra_email_context = None
    form_class = PasswordResetForm
    from_email = None
    html_email_template_name = None
    subject_template_name = "auth/password_reset_subject.txt"
    success_url = reverse_lazy("password_reset_done")
    template_name = "auth/password_reset_form.html"
    title = "Password reset"
    token_generator = default_token_generator

    def form_valid(self, form):
        opts = {
            "use_https": self.request.is_secure(),
            "token_generator": self.token_generator,
            "from_email": self.from_email,
            "email_template_name": self.email_template_name,
            "subject_template_name": self.subject_template_name,
            "html_email_template_name": self.html_email_template_name,
            "extra_email_context": self.extra_email_context,
        }
        form.save(**opts)
        return super().form_valid(form)


INTERNAL_RESET_SESSION_TOKEN = "_password_reset_token"


class PasswordResetDoneView(PasswordContextMixin, TemplateView):
    template_name = "auth/password_reset_done.html"
    title = "Password reset sent"


class PasswordResetConfirmView(PasswordContextMixin, FormView):
    form_class = SetPasswordForm
    post_reset_login = False
    post_reset_login_backend = None
    reset_url_token = "set-password"
    success_url = reverse_lazy("password_reset_complete")
    template_name = "auth/password_reset_confirm.html"
    title = "Enter new password"
    token_generator = default_token_generator

    def get_response(self):
        if "uidb64" not in self.url_kwargs or "token" not in self.url_kwargs:
            raise ImproperlyConfigured(
                "The URL path must contain 'uidb64' and 'token' parameters."
            )

        self.validlink = False
        self.user = self.get_user(self.url_kwargs["uidb64"])

        if self.user is not None:
            token = self.url_kwargs["token"]
            if token == self.reset_url_token:
                session_token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
                if self.token_generator.check_token(self.user, session_token):
                    # If the token is valid, display the password reset form.
                    self.validlink = True
                    response = super().get_response()
                    add_never_cache_headers(response)
                    return response
            else:
                if self.token_generator.check_token(self.user, token):
                    # Store the token in the session and redirect to the
                    # password reset form at a URL without the token. That
                    # avoids the possibility of leaking the token in the
                    # HTTP Referer header.
                    self.request.session[INTERNAL_RESET_SESSION_TOKEN] = token
                    redirect_url = self.request.path.replace(
                        token, self.reset_url_token
                    )
                    response = HttpResponseRedirect(redirect_url)
                    add_never_cache_headers(response)
                    return response

        # Display the "Password reset unsuccessful" page.
        response = self.render_to_response(self.get_template_context())
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
        user = form.save()
        del self.request.session[INTERNAL_RESET_SESSION_TOKEN]
        if self.post_reset_login:
            auth_login(self.request, user, self.post_reset_login_backend)
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


class PasswordResetCompleteView(PasswordContextMixin, TemplateView):
    template_name = "auth/password_reset_complete.html"
    title = "Password reset complete"

    def get_template_context(self):
        context = super().get_template_context()
        context["login_url"] = resolve_url(settings.LOGIN_URL)
        return context


class PasswordChangeView(PasswordContextMixin, AuthViewMixin, FormView):
    form_class = PasswordChangeForm
    success_url = reverse_lazy("password_change_done")
    template_name = "auth/password_change_form.html"
    title = "Password change"
    login_required = True

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


class PasswordChangeDoneView(PasswordContextMixin, AuthViewMixin, TemplateView):
    template_name = "auth/password_change_done.html"
    title = "Password change successful"
    login_required = True
