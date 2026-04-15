from __future__ import annotations

from plain.urls import Router, path

from . import views


class ExamplesRouter(Router):
    namespace = "examples"
    urls = [
        path(
            "forms/create/",
            views.FormsExampleCreateView,
            name="forms_create",
        ),
        path(
            "forms/<int:pk>/update/",
            views.FormsExampleUpdateView,
            name="forms_update",
        ),
    ]
