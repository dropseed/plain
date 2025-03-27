from plain import forms
from plain.auth import get_user_model
from plain.exceptions import ValidationError
from plain.models.forms import ModelForm

from .core import check_user_password
from .hashers import check_password
from .utils import unicode_ci_compare


class PasswordResetForm(forms.Form):
    email = forms.EmailField(max_length=254)

    def send_mail(
        self,
        *,
        template_name: str,
        context: dict,
        from_email: str,
        to_email: str,
    ):
        from plain.email import TemplateEmail

        email = TemplateEmail(
            template=template_name,
            context=context,
            from_email=from_email,
            to=[to_email],
            headers={
                "X-Auto-Response-Suppress": "All",
            },
        )

        email.send()

    def get_users(self, email):
        """Given an email, return matching user(s) who should receive a reset.

        This allows subclasses to more easily customize the default policies
        that prevent inactive users and users with unusable passwords from
        resetting their password.
        """
        active_users = get_user_model()._default_manager.filter(email__iexact=email)
        return (u for u in active_users if unicode_ci_compare(email, u.email))

    def save(
        self,
        *,
        generate_reset_url: callable,
        email_template_name: str = "password_reset",
        from_email: str = "",
        extra_email_context: dict | None = None,
    ):
        """
        Generate a one-use only link for resetting password and send it to the
        user.
        """
        email = self.cleaned_data["email"]
        for user in self.get_users(email):
            context = {
                "email": email,
                "user": user,
                "url": generate_reset_url(user),
                **(extra_email_context or {}),
            }
            self.send_mail(
                template_name=email_template_name,
                context=context,
                from_email=from_email,
                to_email=user.email,
            )


class PasswordSetForm(forms.Form):
    """
    A form that lets a user set their password without entering the old
    password
    """

    new_password1 = forms.CharField(strip=False)
    new_password2 = forms.CharField(strip=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_new_password2(self):
        password1 = self.cleaned_data.get("new_password1")
        password2 = self.cleaned_data.get("new_password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError(
                "The two password fields didn't match.",
                code="password_mismatch",
            )

        # Clean it as if it were being put into the model directly
        self.user._meta.get_field("password").clean(password2, self.user)

        return password2

    def save(self, commit=True):
        self.user.password = self.cleaned_data["new_password1"]
        if commit:
            self.user.save()
        return self.user


class PasswordChangeForm(PasswordSetForm):
    """
    A form that lets a user change their password by entering their old
    password.
    """

    current_password = forms.CharField(strip=False)

    def clean_current_password(self):
        """
        Validate that the current_password field is correct.
        """
        current_password = self.cleaned_data["current_password"]
        if not check_user_password(self.user, current_password):
            raise ValidationError(
                "Your old password was entered incorrectly. Please enter it again.",
                code="password_incorrect",
            )
        return current_password


class PasswordLoginForm(forms.Form):
    email = forms.EmailField(max_length=150)
    password = forms.CharField(strip=False)

    def clean(self):
        User = get_user_model()

        email = self.cleaned_data.get("email")
        password = self.cleaned_data.get("password")

        if email and password:
            try:
                # The vast majority of users won't have a case-sensitive email, so we act that way
                user = User.objects.get(email__iexact=email)
            except User.DoesNotExist:
                # Run the default password hasher once to reduce the timing
                # difference between an existing and a nonexistent user (django #20760).
                check_password(password, "")

                raise ValidationError(
                    "Please enter a correct email and password. Note that both fields may be case-sensitive.",
                    code="invalid_login",
                )

            if not check_user_password(user, password):
                raise ValidationError(
                    "Please enter a correct email and password. Note that both fields may be case-sensitive.",
                    code="invalid_login",
                )

            self._user = user

        return self.cleaned_data

    def get_user(self):
        return self._user


class PasswordSignupForm(ModelForm):
    confirm_password = forms.CharField(strip=False)

    class Meta:
        model = get_user_model()
        fields = ("email", "password")

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        if password and confirm_password and password != confirm_password:
            raise ValidationError(
                "The two password fields didn't match.",
                code="password_mismatch",
            )
        return cleaned_data
