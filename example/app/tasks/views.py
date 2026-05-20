from __future__ import annotations

from typing import Any

from plain.auth.views import AuthView
from plain.forms import Form, Invalid
from plain.htmx.views import HTMXView
from plain.http import RedirectResponse, Response
from plain.postgres.forms import create_from, update_from
from plain.templates.views import DetailView, ListView, TemplateView
from plain.urls import reverse
from plain.views import View

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

    # Set by htmx_post_rename on a rejected rename, so the re-rendered
    # fragment shows the submitted value and its error.
    _title_form: Form | Invalid | None = None

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get_template_context(self) -> dict[str, Any]:
        context = super().get_template_context()
        context["title_form_class"] = TaskTitleForm
        context["title_form"] = self._title_form or TaskTitleForm()
        return context

    def htmx_post_rename(self) -> None:
        result = TaskTitleForm.validate(self.request.form_data)
        if not result:
            self._title_form = result
            return
        self.object.title = result.title
        self.object.save()


class TaskCreateView(AuthView, TemplateView):
    template_name = "tasks/create.html"
    login_required = True

    def get(self) -> Response:
        assert self.user is not None  # login_required
        return self.render_form(TaskForm.for_owner(self.user))

    def post(self) -> Response:
        assert self.user is not None  # login_required
        result = self.validate_form(TaskForm.for_owner(self.user))
        if isinstance(result, Response):
            return result
        # `owner` isn't a form field — pass it to create_from() as an extra.
        create_from(Task, result, owner=self.user)
        return RedirectResponse(reverse("tasks:list"))


class TaskUpdateView(AuthView, DetailView):
    template_name = "tasks/update.html"
    context_object_name = "task"
    login_required = True

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def get(self) -> Response:
        assert self.user is not None  # login_required
        form_class = TaskForm.for_owner(self.user)
        return self.render_form(form_class, values=form_class.initial_from(self.object))

    def post(self) -> Response:
        assert self.user is not None  # login_required
        result = self.validate_form(TaskForm.for_owner(self.user))
        if isinstance(result, Response):
            return result
        update_from(self.object, result)
        return RedirectResponse(reverse("tasks:detail", id=self.object.id))


class TaskDeleteView(AuthView, DetailView):
    template_name = "tasks/delete.html"
    context_object_name = "task"
    login_required = True

    def get_object(self) -> Task | None:
        return Task.query.filter(
            owner=self.user,
            id=self.url_kwargs["id"],
        ).first()

    def post(self) -> Response:
        self.object.delete()
        return RedirectResponse(reverse("tasks:list"))


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
