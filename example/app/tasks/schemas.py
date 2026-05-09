from __future__ import annotations

import datetime
from typing import TypedDict

from app.users.models import User
from plain.postgres.modelschema import ModelSchema
from plain.postgres.query import QuerySet
from plain.schema import Schema, types

from .models import PRIORITY_CHOICES, Project, Tag, Task


class TaskQuickAddSchema(Schema):
    """Scalar-only quick-add schema. Pure plain.schema.Schema — no model
    binding. Useful for the JSON quick-add API where FK/M2M aren't part
    of the input."""

    title: str = types.TextField(max_length=200, min_length=1)
    notes: str | None = types.TextField(required=False, max_length=2000, initial="")
    priority: str | None = types.ChoiceField(choices=PRIORITY_CHOICES, required=False)
    is_complete: bool = types.BooleanField(required=False)


class TaskTitleSchema(Schema):
    """Single-field schema for the HTMX inline-title rename action."""

    title: str = types.TextField(max_length=200, min_length=1)


class TaskSchema(ModelSchema):
    """Full edit/create schema for the Task model. Fields auto-derive from
    Task; FK (project) and M2M (tags) are typed as the related model
    classes. Per-request queryset scoping (owner-filtering) is passed
    via `validate(context={"querysets": {...}})`.

    Cross-field validation (`check()`) runs after fields succeed —
    `is_complete` + future `due_date` is rejected as nonsensical.
    """

    model = Task

    title: str
    notes: str | None
    priority: str
    is_complete: bool
    due_date: datetime.date | None
    project: Project | None
    tags: list[Tag]

    class Querysets(TypedDict, total=False):
        """Per-request queryset scoping for FK/M2M fields. Keys must match
        the FK/M2M field names declared above (validated at class-creation
        time by `ModelSchemaMeta`). Values are typed as the related model's
        QuerySet so a wrong-model queryset is caught at type-check time.
        """

        project: QuerySet[Project]
        tags: QuerySet[Tag]

    def check(self, *, context: dict | None = None) -> dict[str, list[str]] | None:
        if self.is_complete and self.due_date and self.due_date > datetime.date.today():
            return {
                "__all__": [
                    "A task that's already complete can't have a future due date."
                ]
            }
        return None

    @staticmethod
    def querysets_for(user: User) -> TaskSchema.Querysets:
        """Owner-scoped querysets for FK/M2M relation fields."""
        return {
            "project": Project.query.filter(owner=user),
            "tags": Tag.query.filter(owner=user),
        }
