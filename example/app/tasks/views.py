from __future__ import annotations

from functools import cached_property
from typing import Any

from plain.auth.views import AuthView
from plain.htmx.views import HTMXView
from plain.http import NotFoundError404, RedirectResponse, Response
from plain.schema import SchemaForm
from plain.schema.views import SchemaFormView
from plain.templates.views import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)
from plain.urls import reverse, reverse_lazy
from plain.views import View

from .forms import TaskForm, TaskTitleForm
from .models import Project, Tag, Task
from .schemas import TaskSchema


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
        context["title_form"] = TaskTitleForm(request=self.request)
        return context

    def htmx_post_rename(self) -> None:
        form = TaskTitleForm(request=self.request)
        if form.is_valid():
            self.object.title = form.cleaned_data["title"]
            self.object.save()


class TaskCreateView(AuthView, CreateView):
    template_name = "tasks/create.html"
    form_class = TaskForm
    login_required = True

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "owner": self.user}

    def form_valid(self, form: TaskForm) -> Any:  # ty: ignore[invalid-method-override]
        form.instance.owner = self.user
        return super().form_valid(form)


class TaskUpdateView(AuthView, UpdateView):
    template_name = "tasks/update.html"
    form_class = TaskForm
    context_object_name = "task"
    login_required = True

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "owner": self.user}


def _owner_querysets(view: Any) -> dict[str, Any]:
    """FK/M2M querysets scoped to the current user — the scoped schema drives
    both validation and the rendered <select> options, so other users'
    projects and tags are neither selectable nor visible."""
    return {
        "project": Project.query.filter(owner=view.user),
        "tags": Tag.query.filter(owner=view.user),
    }


def _owner_task(view: Any) -> Task:
    """The requested task, scoped to the current user — 404 if it isn't theirs."""
    task = Task.query.filter(owner=view.user, id=view.url_kwargs["id"]).first()
    if not task:
        raise NotFoundError404
    return task


class TaskSchemaCreateView(AuthView, SchemaFormView[TaskSchema]):
    """The plain.schema counterpart to TaskCreateView — the app's
    `SchemaFormView` base instead of `CreateView` + a `ModelForm`."""

    template_name = "tasks/schema_create.html"
    schema_class = TaskSchema
    login_required = True

    def get_schema_form(self) -> SchemaForm[TaskSchema]:
        return SchemaForm(TaskSchema, self.request, querysets=_owner_querysets(self))

    def on_valid(self, result: TaskSchema) -> Response:
        # `owner` isn't a form field — inject it on a fresh Task.
        result.save(Task(owner=self.user))
        return RedirectResponse(reverse("tasks:list"))


class TaskSchemaUpdateView(AuthView, SchemaFormView[TaskSchema]):
    """The plain.schema counterpart to TaskUpdateView. The task is resolved by
    the view's own auth scoping — not a base-class pk lookup — then pre-fills
    the form via `ModelSchema.initial_from()` and is the `save()` target."""

    template_name = "tasks/schema_update.html"
    schema_class = TaskSchema
    login_required = True

    @cached_property
    def task(self) -> Task:
        return _owner_task(self)

    def get_schema_form(self) -> SchemaForm[TaskSchema]:
        return SchemaForm(
            TaskSchema,
            self.request,
            querysets=_owner_querysets(self),
            initial=TaskSchema.initial_from(self.task),
        )

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["task"] = self.task
        return context

    def on_valid(self, result: TaskSchema) -> Response:
        result.save(self.task)
        return RedirectResponse(reverse("tasks:list"))


class TaskSchemaDeleteView(AuthView, TemplateView):
    """The plain.schema counterpart to TaskDeleteView. Delete needs no schema —
    it's a confirmation template plus a `.post()` that deletes the task."""

    template_name = "tasks/schema_delete.html"
    login_required = True

    def get(self) -> Response:
        return self.render(task=_owner_task(self))

    def post(self) -> Response:
        _owner_task(self).delete()
        return RedirectResponse(reverse("tasks:list"))


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
