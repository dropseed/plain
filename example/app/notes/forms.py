from __future__ import annotations

from plain.postgres.modelschema import ModelSchema

from .models import Note


class NoteSchema(ModelSchema):
    model = Note

    title: str
    body: str | None
