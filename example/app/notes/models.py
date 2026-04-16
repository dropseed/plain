from __future__ import annotations

import datetime

from app.users.models import User
from plain import postgres
from plain.postgres import types
from plain.urls import reverse


@postgres.register_model
class Note(postgres.Model):
    author: User = types.ForeignKeyField(
        User,
        on_delete=postgres.CASCADE,
        related_query_name="notes",
    )
    title: str = types.TextField(max_length=200)
    body: str = types.TextField(default="", required=False)
    created_at: datetime.datetime = types.DateTimeField(create_now=True)
    updated_at: datetime.datetime = types.DateTimeField(update_now=True)

    query: postgres.QuerySet[Note] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["-created_at"],
        indexes=[
            postgres.Index(
                name="notes_note_author_created_idx",
                fields=["author", "-created_at"],
            ),
        ],
    )

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("notes:detail", id=self.id)
