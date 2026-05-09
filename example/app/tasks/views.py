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

    def post(self) -> Response:
        # ModelSchema needs a per-request queryset for FK/M2M validation;
        # SchemaView's default post() doesn't pass context. Override here.
        assert self.user is not None  # login_required=True
        result = self.schema_class.validate(
            self.request.form_data,
            files=self.request.files,
            context={"querysets": TaskSchema.querysets_for(self.user)},
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(self.schema_class, result)
            return self.schema_invalid(bound)
        return self.schema_valid(result)

    def schema_valid(self, result: TaskSchema) -> Response:
        # Construct a fresh Task with owner pre-set, then let ModelSchema
        # apply validated fields and save (handling M2M post-PK).
        assert self.user is not None
        task = Task(owner=self.user)
        result.save_to(task)
        self.object = task
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

    def get_initial(self) -> dict[str, Any]:
        return {
            "title": self.object.title,
            "notes": self.object.notes,
            "priority": self.object.priority,
            "is_complete": self.object.is_complete,
            "due_date": self.object.due_date,
            "project": self.object.project_id if self.object.project_id else None,
            "tags": [str(t.id) for t in self.object.tags.query],
        }

    def post(self) -> Response:
        assert self.user is not None
        result = self.schema_class.validate(
            self.request.form_data,
            files=self.request.files,
            context={"querysets": TaskSchema.querysets_for(self.user)},
        )
        if isinstance(result, Invalid):
            bound = BoundSchema.from_invalid(
                self.schema_class, result, initial=self.get_initial()
            )
            return self.schema_invalid(bound)
        return self.schema_valid(result)

    def schema_valid(self, result: TaskSchema) -> Response:
        result.save_to(self.object)
        return RedirectResponse(self.get_success_url(result))


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
