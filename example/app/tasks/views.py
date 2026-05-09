from __future__ import annotations

from typing import Any

from plain.auth.views import AuthView
from plain.htmx.views import HTMXView
from plain.http import JsonResponse, RedirectResponse, Response
from plain.schema import BoundSchema, Invalid
from plain.urls import reverse, reverse_lazy
from plain.views import (
    DeleteView,
    DetailView,
    ListView,
    SchemaCreateView,
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
        # Unbound BoundSchema for the inline title-edit form.
        context["title_form"] = BoundSchema(schema_class=TaskTitleSchema)
        return context

    def htmx_post_rename(self) -> None:
        # Same TaskTitleSchema works for HTMX form-data and JSON bodies —
        # validate() takes any dict-like and returns either the typed
        # schema instance or Invalid. No request kwarg, no .is_valid() dance.
        result = TaskTitleSchema.validate(self.request.form_data)
        if isinstance(result, Invalid):
            return
        task = self.get_object()
        if task is None:
            return
        task.title = result.title
        task.save()

    def htmx_post_validate(self) -> Response:
        """Live per-field validation: same TaskTitleSchema, partial=True.

        Wire this to `hx-trigger="keyup changed delay:300ms"` on the title
        input; returns a JSON shape the client can render as an error
        indicator. The schema runs only on the fields actually present in
        the payload, so missing-required errors don't fire on partial input.
        """
        result = TaskTitleSchema.validate(self.request.form_data, partial=True)
        if isinstance(result, Invalid):
            return JsonResponse({"valid": False, "errors": result.errors})
        return JsonResponse({"valid": True})


class TaskCreateView(AuthView, SchemaCreateView[TaskSchema]):
    """Schema-based create view.

    Replaces the previous CreateView/ModelForm setup. The TaskSchema
    declares fields explicitly; FK/M2M IDs are validated against the
    user's owned Projects/Tags via `resolve_relations()`.
    """

    template_name = "tasks/create.html"
    schema_class = TaskSchema
    login_required = True

    def schema_valid(self, result: TaskSchema) -> Response:
        assert self.user is not None  # guaranteed by login_required=True
        relations = result.resolve_relations(owner=self.user)
        if isinstance(relations, Invalid):
            bound = BoundSchema.from_invalid(TaskSchema, relations)
            return self.schema_invalid(bound)

        task = Task()
        task.owner = self.user
        result.apply_to_task(task, project=relations["project"])
        task.save()
        if relations["tags"]:
            task.tags.set(relations["tags"])

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
        # SchemaUpdateView's default is `getattr(self.object, name)` per field;
        # for FK and M2M we want IDs, not the related instances.
        return {
            "project": self.object.project_id if self.object.project_id else None,
            "title": self.object.title,
            "notes": self.object.notes,
            "due_date": self.object.due_date,
            "priority": self.object.priority,
            "is_complete": self.object.is_complete,
            "tags": [str(t.id) for t in self.object.tags.all()],
        }

    def schema_valid(self, result: TaskSchema) -> Response:
        assert self.user is not None  # guaranteed by login_required=True
        relations = result.resolve_relations(owner=self.user)
        if isinstance(relations, Invalid):
            bound = BoundSchema.from_invalid(
                TaskSchema, relations, initial=self.get_initial()
            )
            return self.schema_invalid(bound)

        result.apply_to_task(self.object, project=relations["project"])
        self.object.save()
        self.object.tags.set(relations["tags"])
        return RedirectResponse(self.get_success_url(result))


class TaskDeleteView(AuthView, DeleteView):
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
    """Convenience: ensures the current user has at least one Project and Tag
    so the create form has something to choose from. Redirects to the list.
    """

    login_required = True

    def get(self) -> Response:
        if not Project.query.filter(owner=self.user).exists():
            Project.query.create(owner=self.user, name="Inbox")
            Project.query.create(owner=self.user, name="Side projects")
        if not Tag.query.filter(owner=self.user).exists():
            for n in ("urgent", "later", "fun"):
                Tag.query.create(owner=self.user, name=n)
        return RedirectResponse(reverse("tasks:list"))
