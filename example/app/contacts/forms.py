from __future__ import annotations

from typing import Any

from plain import forms

from .models import SUBJECT_BUG, SUBJECT_CHOICES, ContactSubmission

BLOCKED_EMAIL_DOMAINS = {"blocked.test", "spam.example"}


class ContactForm(forms.Form):
    """Plain (non-Model) Form exercising every common field type and clean hook.

    Used by ContactView on /contacts/.
    """

    name = forms.TextField(max_length=100, min_length=2)
    email = forms.EmailField()
    subject = forms.ChoiceField(choices=SUBJECT_CHOICES)
    message = forms.TextField(min_length=10)
    subscribe = forms.BooleanField(required=False, initial=False)

    def __init__(self, *, ask_company: bool = False, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if ask_company:
            self.fields["company"] = forms.TextField(max_length=200, required=False)

    def clean_email(self) -> str:
        email: str = self.cleaned_data["email"]
        domain = email.rsplit("@", 1)[-1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS:
            raise forms.ValidationError(f"Email domain '{domain}' is not allowed.")
        return email

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        subject = cleaned.get("subject")
        message = cleaned.get("message", "")
        if subject == SUBJECT_BUG and len(message) < 30:
            raise forms.ValidationError(
                "Bug reports need at least 30 characters of detail."
            )
        return cleaned

    def save(self) -> ContactSubmission:
        return ContactSubmission.query.create(
            name=self.cleaned_data["name"],
            email=self.cleaned_data["email"],
            subject=self.cleaned_data["subject"],
            message=self.cleaned_data["message"],
            company=self.cleaned_data.get("company", ""),
            subscribe=self.cleaned_data["subscribe"],
        )


class ArchiveSearchForm(forms.Form):
    """Plain Form used as a GET search box on the archive page. Uses prefix."""

    prefix = "q"

    text = forms.TextField(required=False)


class ArchiveFilterForm(forms.Form):
    """A second form on the same page as ArchiveSearchForm — proves prefix works."""

    prefix = "f"

    subject = forms.ChoiceField(
        choices=[("", "All subjects")] + SUBJECT_CHOICES,
        required=False,
    )
    subscribed_only = forms.BooleanField(required=False)
