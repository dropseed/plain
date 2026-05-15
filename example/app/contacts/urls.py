from __future__ import annotations

from plain.urls import Router, path

from . import views


class ContactsRouter(Router):
    namespace = "contacts"
    urls = [
        path("", views.ContactView, name="form"),
        path("success", views.ContactSuccessView, name="success"),
        path("archive", views.ContactArchiveView, name="archive"),
        path("schema", views.ContactSchemaView, name="schema"),
        path("schema/success", views.ContactSchemaSuccessView, name="schema_success"),
    ]
