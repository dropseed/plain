from __future__ import annotations

from typing import Any

from plain.schema import Schema, types

from .models import SUBJECT_BUG, SUBJECT_CHOICES

BLOCKED_EMAIL_DOMAINS = {"blocked.test", "spam.example"}


class ContactSchema(Schema):
    """The plain.schema counterpart to ContactForm.

    Same fields and rules as the forms.Form version, expressed as a pure
    validating parser: the per-field and cross-field rules both live in
    check(), and there's no save() — persisting the result is the view's job.
    """

    name = types.TextField(max_length=100, min_length=2)
    email = types.EmailField()
    subject = types.ChoiceField(choices=SUBJECT_CHOICES)
    message = types.TextField(min_length=10)
    company = types.TextField(max_length=200, required=False)
    subscribe = types.BooleanField(required=False)

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        errors: dict[str, list[str]] = {}

        domain = self.email.rsplit("@", 1)[-1].lower()
        if domain in BLOCKED_EMAIL_DOMAINS:
            errors["email"] = [f"Email domain '{domain}' is not allowed."]

        if self.subject == SUBJECT_BUG and len(self.message) < 30:
            errors["message"] = ["Bug reports need at least 30 characters of detail."]

        return errors or None
