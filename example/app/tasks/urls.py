from __future__ import annotations

from plain.urls import Router, path

from . import views


class TasksRouter(Router):
    namespace = "tasks"
    urls = [
        path("", views.TaskListView, name="list"),
        path("seed", views.TaskSeedView, name="seed"),
        path("new", views.TaskCreateView, name="create"),
        path("schema/new", views.TaskSchemaCreateView, name="schema_create"),
        path("schema/<int:id>/edit", views.TaskSchemaUpdateView, name="schema_update"),
        path(
            "schema/<int:id>/delete",
            views.TaskSchemaDeleteView,
            name="schema_delete",
        ),
        path("<int:id>", views.TaskDetailView, name="detail"),
        path("<int:id>/edit", views.TaskUpdateView, name="update"),
        path("<int:id>/delete", views.TaskDeleteView, name="delete"),
    ]
