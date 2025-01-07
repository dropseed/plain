from plain.auth import get_user_model
from plain.mail import TemplateEmail
from plain.models.forms import ModelForm
from plain.runtime import settings

from .models import SupportFormEntry


class SupportForm(ModelForm):
    """
    The form is the customization point for users.
    So any behavior modifications should be possible here.
    """

    class Meta:
        model = SupportFormEntry
        fields = ["name", "email", "message"]

    def __init__(self, user, form_slug, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user  # User provided directly by authed request
        self.form_slug = form_slug
        if self.user:
            self.fields["email"].initial = user.email

    def find_user(self):
        # If the user isn't logged in (typical in an iframe, depending on session cookie settings),
        # we can still try to look them up by email
        # to associate the entry with them.
        #
        # Note that since they aren't logged in, this doesn't necessarily
        # confirm that this wasn't an impersonation attempt.
        # Subsequent conversations over email will confirm that they have access to the email.
        email = self.cleaned_data.get("email")
        if not email:
            return None
        UserModel = get_user_model()
        try:
            return UserModel.objects.get(email=email)
        except UserModel.DoesNotExist:
            return

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.user = self.user or self.find_user()
        instance.form_slug = self.form_slug
        if commit:
            instance.save()
        return instance

    def notify(self, instance):
        """
        Notify the support team of a new support form entry.

        Sends an immediate email by default.
        """
        email = TemplateEmail(
            template="support_form_entry",
            subject=f"Support request from {instance.name}",
            to=[settings.SUPPORT_EMAIL],
            reply_to=[instance.email],
            context={
                "support_form_entry": instance,
            },
        )
        email.send()
