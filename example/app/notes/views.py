from __future__ import annotations

from plain.auth.views import AuthView
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


class NoteListView(AuthView, ListView):
    template_name = "notes/list.html"
    context_object_name = "notes"
    login_required = True

    def get_objects(self) -> list[Note]:
        return list(Note.query.filter(author=self.user))


class NoteDetailView(AuthView, DetailView):
    template_name = "notes/detail.html"
    context_object_name = "note"
    login_required = True

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()


class NoteCreateView(AuthView, SchemaCreateView[NoteSchema]):
    template_name = "notes/create.html"
    schema_class = NoteSchema
    login_required = True

    def schema_valid(self, result: NoteSchema) -> Response:
        # Author isn't a schema field — set on the instance before saving.
        assert self.user is not None
        self.object = result.save(Note(author=self.user))
        return super().schema_valid(result)


class NoteUpdateView(AuthView, SchemaUpdateView[NoteSchema]):
    template_name = "notes/update.html"
    schema_class = NoteSchema
    context_object_name = "note"
    login_required = True

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()


class NoteDeleteView(AuthView, SchemaDeleteView):
    template_name = "notes/delete.html"
    context_object_name = "note"
    login_required = True
    success_url = reverse_lazy("notes:list")

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()
