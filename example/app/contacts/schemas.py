"""Schema-based parallel to contacts/forms.py — same behavior, no Form
class. Demonstrates the Schema + BoundSchema rebuild against the existing
contacts/form.html template (which is duck-typed against the Form
interface).

What's lost vs ContactForm:
  - Per-instance dynamic field (ask_company) — replaced by always-declaring
    the field with required=False and rendering conditionally in the view.
  - .save() method on the form — moved to the view body.

What's gained:
  - validate() is a pure classmethod — works in jobs / scripts / tests
    without a request fake.
  - The validated instance IS the typed schema — `result.email` is `str`,
    no `.data` indirection, no narrowing wart.
  - Cross-field check() (instance method, naturally typed `self`) and
    per-email validation via plain validators.
"""

from __future__ import annotations

from typing import Any

from plain.exceptions import ValidationError
from plain.schema import Schema, types

from .models import SUBJECT_BUG, SUBJECT_CHOICES

BLOCKED_EMAIL_DOMAINS = {"blocked.test", "spam.example"}


def _disallow_blocked_email(value: str) -> None:
    domain = value.rsplit("@", 1)[-1].lower()
    if domain in BLOCKED_EMAIL_DOMAINS:
        raise ValidationError(f"Email domain '{domain}' is not allowed.")


class ContactSchema(Schema):
    """Parallel to ContactForm — same fields, same validation rules."""

    name: str = types.TextField(max_length=100, min_length=2)
    email: str = types.EmailField(validators=[_disallow_blocked_email])
    subject: str = types.ChoiceField(choices=SUBJECT_CHOICES)
    message: str = types.TextField(min_length=10)
    subscribe: bool = types.BooleanField(required=False, initial=False)
    # Always declared; ContactSchemaView only renders this field when
    # ?company=1 is set (matching ContactForm.ask_company behavior).
    company: str | None = types.TextField(max_length=200, required=False, initial="")

    def check(self, *, context: dict | None = None) -> dict[str, list[str]] | None:
        """Cross-field: bug reports need at least 30 characters of detail."""
        if self.subject == SUBJECT_BUG and len(self.message) < 30:
            return {"__all__": ["Bug reports need at least 30 characters of detail."]}
        return None


class AttachmentUploadSchema(Schema):
    """File-upload demo. Plain.schema receives `request.files` as a kwarg
    and dispatches FileField fields to it; everything else continues to
    read from `request.form_data`.

    Constraints exercise the FileField surface: max filename length and
    requiredness via the standard Schema mechanism. The Any annotation
    on `document` is intentional — UploadedFile is opaque to ty (it lives
    in plain.internal.files), and tests don't need its full type to
    assert .name and .size attributes."""

    description: str = types.TextField(min_length=1, max_length=500)
    document: Any = types.FileField(max_length=120)
