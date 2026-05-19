from __future__ import annotations

from plain.forms import Error, Form, types

from .models import SUBJECT_BUG, SUBJECT_CHOICES

BLOCKED_EMAIL_DOMAINS = {"blocked.test", "spam.example"}


class ContactForm(Form):
    """A plain (non-model) Form exercising common field types and the
    cross-field `check()` hook. `ContactView` validates it, then copies the
    cleaned values onto a `ContactSubmission`.
    """

    name = types.TextField(max_length=100, min_length=2)
    email = types.EmailField()
    subject = types.ChoiceField(choices=SUBJECT_CHOICES)
    message = types.TextField(min_length=10)
    subscribe = types.BooleanField(required=False)

    def check(self) -> list[Error] | None:
        """Validation that spans fields, or that a single field can't express
        on its own — run after every field has cleaned."""
        errors: list[Error] = []

        domain = self.email.rsplit("@", 1)[-1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS:
            errors.append(
                Error(
                    f"Email domain '{domain}' is not allowed.",
                    code="blocked_domain",
                    field="email",
                )
            )

        if self.subject == SUBJECT_BUG and len(self.message) < 30:
            errors.append(
                Error(
                    "Bug reports need at least 30 characters of detail.",
                    code="too_short",
                    field="message",
                )
            )

        return errors or None


class ContactFormWithCompany(ContactForm):
    """`ContactForm` plus an optional `company` field. `ContactView` swaps to
    this when `?company=1` — a conditional field is a subclass now, not a
    per-instance `self.fields[...]` mutation.
    """

    company = types.TextField(max_length=200, required=False)
