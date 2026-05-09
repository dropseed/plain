from __future__ import annotations

from plain.auth.views import LoginRequiredView
from plain.http import Response
from plain.urls import reverse_lazy
from plain.views import (
    DetailView,
    ListView,
    SchemaCreateView,
    SchemaDeleteView,
    SchemaUpdateView,
)

from .forms import NoteSchema
from .models import Note


class NoteListView(LoginRequiredView, ListView[Note]):
    template_name = "notes/list.html"
    context_object_name = "notes"

    def get_objects(self) -> list[Note]:
        return list(Note.query.filter(author=self.user))


class NoteDetailView(LoginRequiredView, DetailView[Note]):
    template_name = "notes/detail.html"
    context_object_name = "note"

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()


class NoteCreateView(LoginRequiredView, SchemaCreateView[NoteSchema, Note]):
    template_name = "notes/create.html"

    def schema_valid(self, result: NoteSchema) -> Response:
        # Author isn't a schema field — set on the instance before saving.
        self.object = result.save(Note(author=self.user))
        return super().schema_valid(result)


class NoteUpdateView(LoginRequiredView, SchemaUpdateView[NoteSchema, Note]):
    template_name = "notes/update.html"
    context_object_name = "note"

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()


class NoteDeleteView(LoginRequiredView, SchemaDeleteView[Note]):
    template_name = "notes/delete.html"
    context_object_name = "note"
    success_url = reverse_lazy("notes:list")

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()
