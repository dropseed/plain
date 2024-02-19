import unicodedata

from bolt import forms
from bolt.auth import get_user_model
from bolt.db.forms import ModelForm
from bolt.exceptions import ValidationError
from bolt.mail import EmailMultiAlternatives
from bolt.passwords import validators
from bolt.passwords.tokens import default_token_generator
from bolt.templates import Template
from bolt.utils.encoding import force_bytes
from bolt.utils.http import urlsafe_base64_encode


def _unicode_ci_compare(s1, s2):
    """
    Perform case-insensitive comparison of two identifiers, using the
    recommended algorithm from Unicode Technical Report 36, section
    2.11.2(B)(2).
    """
    return (
        unicodedata.normalize("NFKC", s1).casefold()
        == unicodedata.normalize("NFKC", s2).casefold()
    )


class UsernameField(forms.CharField):
    def to_python(self, value):
        return unicodedata.normalize("NFKC", super().to_python(value))

    def widget_attrs(self, widget):
        return {
            **super().widget_attrs(widget),
            "autocapitalize": "none",
            "autocomplete": "username",
        }


class BaseUserCreationForm(ModelForm):
    """
    A form that creates a user, with no privileges, from the given username and
    password.
    """

    error_messages = {
        "password_mismatch": "The two password fields didn’t match.",
    }
    password1 = forms.CharField(
        # label="Password",
        strip=False,
        # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        # help_text=validators.password_validators_help_text_html(),
    )
    password2 = forms.CharField(
        # label="Password confirmation",
        # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
        # help_text="Enter the same password as before, for verification.",
    )

    class Meta:
        model = get_user_model()
        fields = ("username",)
        field_classes = {"username": UsernameField}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self._meta.model.USERNAME_FIELD in self.fields:
            self.fields[self._meta.model.USERNAME_FIELD].widget.attrs[
                "autofocus"
            ] = True

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(
                self.error_messages["password_mismatch"],
                code="password_mismatch",
            )
        return password2

    def _post_clean(self):
        super()._post_clean()
        # Validate the password after self.instance is updated with form data
        # by super().
        password = self.cleaned_data.get("password2")
        if password:
            try:
                validators.validate_password(password, self.instance)
            except ValidationError as error:
                self.add_error("password2", error)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
            if hasattr(self, "save_m2m"):
                self.save_m2m()
        return user


class UserCreationForm(BaseUserCreationForm):
    error_messages = {
        **BaseUserCreationForm.error_messages,
        "unique": "A user with that username already exists.",
    }

    def clean_username(self):
        """Reject usernames that differ only in case."""
        username = self.cleaned_data.get("username")
        if (
            username
            and get_user_model().objects.filter(username__iexact=username).exists()
        ):
            raise forms.ValidationError(self.error_messages["unique"], code="unique")
        else:
            return username


class PasswordResetForm(forms.Form):
    email = forms.EmailField(
        # label="Email",
        max_length=254,
        # widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        """
        Send a bolt.mail.EmailMultiAlternatives to `to_email`.
        """
        template = Template(subject_template_name)
        subject = template.render(context)
        # Email subject *must not* contain newlines
        subject = "".join(subject.splitlines())
        template = Template(email_template_name)
        body = template.render(context)

        email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])
        if html_email_template_name is not None:
            template = Template(html_email_template_name)
            html_email = template.render(context)
            email_message.attach_alternative(html_email, "text/html")

        email_message.send()

    def get_users(self, email):
        """Given an email, return matching user(s) who should receive a reset.

        This allows subclasses to more easily customize the default policies
        that prevent inactive users and users with unusable passwords from
        resetting their password.
        """
        active_users = get_user_model()._default_manager.filter(email__iexact=email)
        return (u for u in active_users if _unicode_ci_compare(email, u.email))

    def save(
        self,
        subject_template_name="auth/password_reset_subject.txt",
        email_template_name="auth/password_reset_email.html",
        use_https=False,
        token_generator=default_token_generator,
        from_email=None,
        html_email_template_name=None,
        extra_email_context=None,
    ):
        """
        Generate a one-use only link for resetting password and send it to the
        user.
        """
        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            context = {
                "email": user.email,
                "uid": urlsafe_base64_encode(force_bytes(user.pk)),
                "user": user,
                "token": token_generator.make_token(user),
                "protocol": "https" if use_https else "http",
                **(extra_email_context or {}),
            }
            self.send_mail(
                subject_template_name,
                email_template_name,
                context,
                from_email,
                user.email,
                html_email_template_name=html_email_template_name,
            )


class SetPasswordForm(forms.Form):
    """
    A form that lets a user set their password without entering the old
    password
    """

    error_messages = {
        "password_mismatch": "The two password fields didn’t match.",
    }
    new_password1 = forms.CharField(
        # label="New password",
        # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        strip=False,
        # help_text=validators.password_validators_help_text_html(),
    )
    new_password2 = forms.CharField(
        # label="New password confirmation",
        strip=False,
        # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(
                self.error_messages["password_mismatch"],
                code="password_mismatch",
            )
        validators.validate_password(password2, self.user)
        return password2

    def save(self, commit=True):
        password = self.cleaned_data["new_password1"]
        self.user.set_password(password)
        if commit:
            self.user.save()
        return self.user


class PasswordChangeForm(SetPasswordForm):
    """
    A form that lets a user change their password by entering their old
    password.
    """

    error_messages = {
        **SetPasswordForm.error_messages,
        "password_incorrect": "Your old password was entered incorrectly. Please enter it again.",
    }
    old_password = forms.CharField(
        # label="Old password",
        strip=False,
        # widget=forms.PasswordInput(
        #     attrs={"autocomplete": "current-password", "autofocus": True}
        # ),
    )

    field_order = ["old_password", "new_password1", "new_password2"]

    def clean_old_password(self):
        """
        Validate that the old_password field is correct.
        """
        old_password = self.cleaned_data["old_password"]
        if not self.user.check_password(old_password):
            raise ValidationError(
                self.error_messages["password_incorrect"],
                code="password_incorrect",
            )
        return old_password
