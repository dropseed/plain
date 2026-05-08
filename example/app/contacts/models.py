from __future__ import annotations

import datetime

from plain import postgres
from plain.postgres import types

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
    name: str = types.TextField(max_length=100)
    email: str = types.EmailField()
    subject: str = types.TextField(max_length=20, choices=SUBJECT_CHOICES)
    message: str = types.TextField()
    company: str = types.TextField(max_length=200, default="", required=False)
    subscribe: bool = types.BooleanField(default=False)
    created_at: datetime.datetime = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[ContactSubmission] = postgres.QuerySet()

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
