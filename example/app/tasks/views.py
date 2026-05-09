from __future__ import annotations

from typing import Any

from plain.auth.views import AuthView
from plain.htmx.views import HTMXView
from plain.http import JsonResponse, RedirectResponse, Response
from plain.schema import BoundSchema, Invalid
from plain.urls import reverse, reverse_lazy
from plain.views import (
    DetailView,
    ListView,
    SchemaCreateView,
    SchemaDeleteView,
    SchemaUpdateView,
    View,
)

from .models import Project, Tag, Task
from .schemas import TaskSchema, TaskTitleSchema


class TaskListView(AuthView, ListView):
    template_name = "tasks/list.html"
    context_object_name = "tasks"
    login_required = True

    def get_objects(self) -> list[Task]:
        return list(
            Task.query.filter(owner=self.user)
            .select_related("project")
            .prefetch_related("tags")[:100]
        )


class TaskDetailView(AuthView, HTMXView, DetailView):
    """Detail page that also serves the HTMX inline-edit fragment.

    plain-hx-action="rename" → htmx_post_rename swaps the rendered title.
    """

    template_name = "tasks/detail.html"
    context_object_name = "task"
    login_required = True

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["title_form"] = BoundSchema(schema_class=TaskTitleSchema)
        return context

    def htmx_post_rename(self) -> None:
        result = TaskTitleSchema.validate(self.request.form_data)
        if isinstance(result, Invalid):
            return
        task = self.get_object()
        if task is None:
            return
        task.title = result.title
        task.save()

    def htmx_post_validate(self) -> Response:
        result = TaskTitleSchema.validate(self.request.form_data, partial=True)
        if isinstance(result, Invalid):
            return JsonResponse({"valid": False, "errors": result.errors})
        return JsonResponse({"valid": True})


class TaskCreateView(AuthView, SchemaCreateView[TaskSchema]):
    """Create a Task using the auto-derived TaskSchema (ModelSchema)."""

    template_name = "tasks/create.html"
    schema_class = TaskSchema
    login_required = True

    def get_querysets(self) -> dict[str, Any]:
        assert self.user is not None  # login_required=True
        return TaskSchema.querysets_for(self.user)

    def schema_valid(self, result: TaskSchema) -> Response:
        # Construct a Task with owner pre-set, then let ModelSchema
        # apply validated fields, save, and handle M2M.
        assert self.user is not None
        self.object = result.save(Task(owner=self.user))
        return super().schema_valid(result)


class TaskUpdateView(AuthView, SchemaUpdateView[TaskSchema]):
    template_name = "tasks/update.html"
    schema_class = TaskSchema
    context_object_name = "task"
    login_required = True

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get_querysets(self) -> dict[str, Any]:
        assert self.user is not None
        return TaskSchema.querysets_for(self.user)


class TaskDeleteView(AuthView, SchemaDeleteView):
    template_name = "tasks/delete.html"
    context_object_name = "task"
    login_required = True
    success_url = reverse_lazy("tasks:list")

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()


class TaskSeedView(AuthView, View):
    """Convenience: ensures the current user has at least one Project and Tag."""

    login_required = True

    def get(self) -> Response:
        if not Project.query.filter(owner=self.user).exists():
            Project.query.create(owner=self.user, name="Inbox")
            Project.query.create(owner=self.user, name="Side projects")
        if not Tag.query.filter(owner=self.user).exists():
            for n in ("urgent", "later", "fun"):
                Tag.query.create(owner=self.user, name=n)
        return RedirectResponse(reverse("tasks:list"))
