from plain import forms
from plain.auth import get_user_model
from plain.mail import TemplateEmail

from .links import generate_link_url


class LoginLinkForm(forms.Form):
    email = forms.EmailField()
    next = forms.CharField(required=False)

    def maybe_send_link(self, request, expires_in=60 * 60):
        user_model = get_user_model()
        email = self.cleaned_data["email"]
        try:
            user = user_model.objects.get(email__iexact=email)
        except user_model.DoesNotExist:
            user = None

        if user:
            url = generate_link_url(
                request=request, user=user, email=email, expires_in=expires_in
            )

            if next_url := self.cleaned_data.get("next"):
                url += f"?next={next_url}"

            email = self.get_email_template(
                email=email,
                context={"user": user, "url": url, "expires_in": expires_in},
            )
            return email.send()

    def get_email_template(self, *, email, context):
        """
        Create the TemplateEmail object

        Override this if you want to change the subject, template, etc.
        """
        return TemplateEmail(
            template="loginlink",
            subject="Your link to log in",
            to=[email],
            context=context,
        )
