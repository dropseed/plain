from __future__ import annotations

from plain.auth.views import AuthView
from plain.forms import FormDisplay
from plain.html.views import DetailView, ListView, TemplateView
from plain.http import RedirectResponse, Response
from plain.postgres.forms import create_from, update_from
from plain.urls import reverse

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


class NoteCreateView(AuthView, TemplateView):
    template_name = "notes/create.html"
    login_required = True

    def get(self) -> Response:
        return self.render(form=FormDisplay(NoteForm))

    def post(self) -> Response:
        result = NoteForm.validate(self.request.form_data)
        if not result:
            return self.render(form=FormDisplay(NoteForm, result))
        # `author` isn't a form field — pass it to create_from() as an extra.
        note = create_from(Note, result, author=self.user)
        return RedirectResponse(note.get_absolute_url())


class NoteUpdateView(AuthView, DetailView):
    template_name = "notes/update.html"
    context_object_name = "note"
    login_required = True

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get(self) -> Response:
        return self.render(
            form=FormDisplay(NoteForm, values=NoteForm.initial_from(self.object))
        )

    def post(self) -> Response:
        result = NoteForm.validate(self.request.form_data)
        if not result:
            return self.render(form=FormDisplay(NoteForm, result))
        update_from(self.object, result)
        return RedirectResponse(self.object.get_absolute_url())


class NoteDeleteView(AuthView, DetailView):
    template_name = "notes/delete.html"
    context_object_name = "note"
    login_required = True

    def get_object(self) -> Note | None:
        return Note.query.filter(
            author=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def post(self) -> Response:
        self.object.delete()
        return RedirectResponse(reverse("notes:list"))
