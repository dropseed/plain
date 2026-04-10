from __future__ import annotations

from plain.urls import Router, path

from . import views


class NotesRouter(Router):
    namespace = "notes"
    urls = [
        path("", views.NoteListView, name="list"),
        path("new/", views.NoteCreateView, name="create"),
        path("<int:id>/", views.NoteDetailView, name="detail"),
        path("<int:id>/edit/", views.NoteUpdateView, name="update"),
        path("<int:id>/delete/", views.NoteDeleteView, name="delete"),
    ]
