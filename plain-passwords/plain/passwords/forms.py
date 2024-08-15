from plain import forms
from plain.auth import get_user_model
from plain.exceptions import ValidationError
from plain.models.forms import ModelForm

from .core import check_user_password
from .hashers import check_password

# class PasswordResetForm(forms.Form):
#     email = forms.EmailField(
#         # label="Email",
#         max_length=254,
#         # widget=forms.EmailInput(attrs={"autocomplete": "email"}),
#     )

#     def send_mail(
#         self,
#         subject_template_name,
#         email_template_name,
#         context,
#         from_email,
#         to_email,
#         html_email_template_name=None,
#     ):
#         from plain.mail import EmailMultiAlternatives

#         """
#         Send a plain.mail.EmailMultiAlternatives to `to_email`.
#         """
#         template = Template(subject_template_name)
#         subject = template.render(context)
#         # Email subject *must not* contain newlines
#         subject = "".join(subject.splitlines())
#         template = Template(email_template_name)
#         body = template.render(context)

#         email_message = EmailMultiAlternatives(subject, body, from_email, [to_email])
#         if html_email_template_name is not None:
#             template = Template(html_email_template_name)
#             html_email = template.render(context)
#             email_message.attach_alternative(html_email, "text/html")

#         email_message.send()

#     def get_users(self, email):
#         """Given an email, return matching user(s) who should receive a reset.

#         This allows subclasses to more easily customize the default policies
#         that prevent inactive users and users with unusable passwords from
#         resetting their password.
#         """
#         active_users = get_user_model()._default_manager.filter(email__iexact=email)
#         return (u for u in active_users if _unicode_ci_compare(email, u.email))

#     def save(
#         self,
#         subject_template_name="auth/password_reset_subject.txt",
#         email_template_name="auth/password_reset_email.html",
#         use_https=False,
#         token_generator=default_token_generator,
#         from_email=None,
#         html_email_template_name=None,
#         extra_email_context=None,
#     ):
#         """
#         Generate a one-use only link for resetting password and send it to the
#         user.
#         """
#         email = self.cleaned_data["email"]
#         for user in self.get_users(email):
#             context = {
#                 "email": user.email,
#                 "uid": urlsafe_base64_encode(force_bytes(user.pk)),
#                 "user": user,
#                 "token": token_generator.make_token(user),
#                 "protocol": "https" if use_https else "http",
#                 **(extra_email_context or {}),
#             }
#             self.send_mail(
#                 subject_template_name,
#                 email_template_name,
#                 context,
#                 from_email,
#                 user.email,
#                 html_email_template_name=html_email_template_name,
#             )


# class SetPasswordForm(forms.Form):
#     """
#     A form that lets a user set their password without entering the old
#     password
#     """

#     error_messages = {
#         "password_mismatch": "The two password fields didn’t match.",
#     }
#     new_password1 = forms.CharField(
#         # label="New password",
#         # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
#         strip=False,
#         # help_text=validators.password_validators_help_text_html(),
#     )
#     new_password2 = forms.CharField(
#         # label="New password confirmation",
#         strip=False,
#         # widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
#     )

#     def __init__(self, user, *args, **kwargs):
#         self.user = user
#         super().__init__(*args, **kwargs)

#     def clean_new_password2(self):
#         password1 = self.cleaned_data.get("new_password1")
#         password2 = self.cleaned_data.get("new_password2")
#         if password1 and password2 and password1 != password2:
#             raise ValidationError(
#                 self.error_messages["password_mismatch"],
#                 code="password_mismatch",
#             )
#         validators.validate_password(password2, self.user)
#         return password2

#     def save(self, commit=True):
#         password = self.cleaned_data["new_password1"]
#         self.user.set_password(password)
#         if commit:
#             self.user.save()
#         return self.user


# class PasswordChangeForm(SetPasswordForm):
#     """
#     A form that lets a user change their password by entering their old
#     password.
#     """

#     error_messages = {
#         **SetPasswordForm.error_messages,
#         "password_incorrect": "Your old password was entered incorrectly. Please enter it again.",
#     }
#     old_password = forms.CharField(
#         # label="Old password",
#         strip=False,
#         # widget=forms.PasswordInput(
#         #     attrs={"autocomplete": "current-password", "autofocus": True}
#         # ),
#     )

#     field_order = ["old_password", "new_password1", "new_password2"]

#     def clean_old_password(self):
#         """
#         Validate that the old_password field is correct.
#         """
#         old_password = self.cleaned_data["old_password"]
#         if not self.user.check_password(old_password):
#             raise ValidationError(
#                 self.error_messages["password_incorrect"],
#                 code="password_incorrect",
#             )
#         return old_password


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
