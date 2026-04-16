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
        path(
            "child-cascade/create/",
            views.ChildCascadeCreateView,
            name="child_cascade_create",
        ),
        path(
            "db-defaults/create/",
            views.DBDefaultsExampleCreateView,
            name="db_defaults_create",
        ),
        path(
            "secret-store/create/",
            views.SecretStoreCreateView,
            name="secret_store_create",
        ),
    ]
