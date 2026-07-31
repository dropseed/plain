from __future__ import annotations

from datetime import datetime

from plain import postgres
from plain.postgres import Field, types

SUBJECT_GENERAL = "general"
SUBJECT_BUG = "bug"
SUBJECT_FEATURE = "feature"
SUBJECT_BILLING = "billing"

SUBJECT_CHOICES = [
    (SUBJECT_GENERAL, "General question"),
    (SUBJECT_BUG, "Bug report"),
    (SUBJECT_FEATURE, "Feature request"),
    (SUBJECT_BILLING, "Billing"),
]


@postgres.register_model
class ContactSubmission(postgres.Model):
    name: Field[str] = types.TextField(max_length=100)
    email: Field[str] = types.EmailField()
    subject: Field[str] = types.TextField(max_length=20, choices=SUBJECT_CHOICES)
    message: Field[str] = types.TextField()
    company: Field[str] = types.TextField(max_length=200, default="", required=False)
    subscribe: Field[bool] = types.BooleanField(default=False)
    created_at: Field[datetime] = types.DateTimeField(create_now=True)

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="contacts_subj_created_idx",
                fields=["subject", "-created_at"],
            ),
        ],
    )

    def __str__(self) -> str:
        return f"{self.name} — {self.subject}"
