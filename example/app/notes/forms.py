from __future__ import annotations

from plain.postgres.forms import ModelForm, model_field

from .models import Note


class NoteForm(ModelForm):
    """A ModelForm over Note. `author` is not a form field — the create view
    passes it to `create_from()` as an extra."""

    title = model_field(Note.title)
    body = model_field(Note.body)
