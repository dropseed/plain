from __future__ import annotations

import datetime
from typing import Any

from plain.schema.modelschema import ModelSchema

from .models import Project, Tag, Task


class TaskSchema(ModelSchema):
    """The plain.schema counterpart to TaskForm.

    Fields auto-derive from the Task model: scalar columns become types.*
    fields, the project ForeignKey becomes a ModelChoiceField, and the tags
    ManyToMany becomes a ModelMultipleChoiceField. `owner` is left out — the
    view sets it on the instance before save.
    """

    model = Task

    project: Project | None
    title: str
    notes: str
    due_date: datetime.date | None
    priority: str
    is_complete: bool
    tags: list[Tag]

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        if self.is_complete and self.due_date and self.due_date > datetime.date.today():
            return {"due_date": ["A completed task can't have a future due date."]}
        return None
