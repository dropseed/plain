from __future__ import annotations

from plain.postgres.forms import ModelForm

from .models import Note


class NoteForm(ModelForm):
    class Meta:
        model = Note
        fields = ("title", "body")
