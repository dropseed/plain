from __future__ import annotations

from typing import Any

from plain.auth.views import AuthView
from plain.htmx.views import HTMXView
from plain.http import RedirectResponse, Response
from plain.urls import reverse, reverse_lazy
from plain.views import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    View,
)

from .forms import TaskForm, TaskTitleForm
from .models import Project, Tag, Task


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
