from __future__ import annotations

from typing import Any

from plain.auth.views import AuthView
from plain.forms import BaseForm
from plain.urls import reverse_lazy
from plain.views import CreateView, DeleteView, DetailView, ListView, UpdateView

from .forms import NoteForm
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


class NoteCreateView(AuthView, CreateView):
    template_name = "notes/create.html"
    form_class = NoteForm
    login_required = True

    def form_valid(self, form: BaseForm) -> Any:
        # Author isn't a form field — set it on the instance before save.
        assert isinstance(form, NoteForm)
        form.instance.author = self.user
        return super().form_valid(form)


class NoteUpdateView(AuthView, UpdateView):
    template_name = "notes/update.html"
    form_class = NoteForm
    context_object_name = "note"
    login_required = True

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()


class NoteDeleteView(AuthView, DeleteView):
    template_name = "notes/delete.html"
    context_object_name = "note"
    login_required = True
    success_url = reverse_lazy("notes:list")

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()
