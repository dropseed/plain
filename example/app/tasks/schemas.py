from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

from plain.schema import Invalid, Schema, types

from .models import PRIORITY_CHOICES, Project, Tag, Task

if TYPE_CHECKING:
    from app.users.models import User


class TaskQuickAddSchema(Schema):
    """Scalar-only quick-add schema. Parallel to TaskTitleForm but pure
    data — no request, no rendering, no model save magic."""

    title: str = types.TextField(max_length=200, min_length=1)
    notes: str | None = types.TextField(required=False, max_length=2000, initial="")
    priority: str | None = types.ChoiceField(choices=PRIORITY_CHOICES, required=False)
    is_complete: bool = types.BooleanField(required=False)


class TaskTitleSchema(Schema):
    """Single-field schema for the HTMX inline-title rename action."""

    title: str = types.TextField(max_length=200, min_length=1)


class TaskSchema(Schema):
    """Full edit/create schema, parallel to the previous ModelForm-based
    TaskForm. Same fields as Task model, declared explicitly. FK (project)
    and M2M (tags) fields hold IDs; the view resolves them against an
    owner-scoped queryset.

    The previous TaskForm used `ModelChoiceField(queryset=...)` to validate
    that submitted FK/M2M IDs belonged to the user. Here, `apply_to_task()`
    does that resolution explicitly with `Project.query.get(id=..., owner=...)`,
    raising Invalid-shaped errors on mismatch. More code, but every step
    is visible and the type checker understands the boundary.
    """

    project: int | None = types.IntegerField(required=False)
    title: str = types.TextField(max_length=200, min_length=1)
    notes: str | None = types.TextField(required=False, initial="")
    due_date: datetime.date | None = types.DateField(required=False)
    priority: str = types.ChoiceField(choices=PRIORITY_CHOICES)
    is_complete: bool = types.BooleanField(required=False)
    tags: list[str] = types.MultipleChoiceField(choices=[], required=False)

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        if self.is_complete and self.due_date and self.due_date > datetime.date.today():
            return {
                "__all__": [
                    "A task that's already complete can't have a future due date."
                ]
            }
        return None

    def resolve_relations(self, *, owner: User) -> Invalid | dict[str, Any]:
        """Look up FK/M2M targets scoped to `owner`. Returns either a dict of
        {project: Project|None, tags: list[Tag]} or an Invalid carrying the
        per-field errors. Called from the view after `validate()` succeeds."""
        errors: dict[str, list[str]] = {}

        project: Project | None = None
        if self.project is not None:
            try:
                project = Project.query.get(id=self.project, owner=owner)
            except Project.DoesNotExist:
                errors["project"] = ["Select a valid project."]

        tag_ids = [int(t) for t in (self.tags or []) if t]
        tags = list(Tag.query.filter(id__in=tag_ids, owner=owner)) if tag_ids else []
        if len(tags) != len(tag_ids):
            errors["tags"] = ["One or more selected tags are not available."]

        if errors:
            return Invalid(
                errors=errors,
                raw={"project": self.project, "tags": list(self.tags or [])},
            )
        return {"project": project, "tags": tags}

    def apply_to_task(self, task: Task, *, project: Project | None) -> Task:
        """Apply scalar + FK fields to a Task instance. M2M (tags) are set
        separately by the caller after the instance has a primary key."""
        task.title = self.title
        task.notes = self.notes or ""
        task.due_date = self.due_date
        task.priority = self.priority
        task.is_complete = self.is_complete
        task.project = project
        return task
