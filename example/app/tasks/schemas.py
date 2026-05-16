from __future__ import annotations

import datetime
from typing import Any

from plain.schema import Field
from plain.schema.modelschema import ModelSchema, model_field

from .models import Project, Tag, Task


class TaskSchema(ModelSchema):
    """The plain.schema counterpart to TaskForm.

    Fields auto-derive from the Task model: scalar columns become types.*
    fields, the project ForeignKey becomes a ModelChoiceField, and the tags
    ManyToMany becomes a ModelMultipleChoiceField. `owner` is left out — the
    view sets it on the instance before save.
    """

    model = Task

    project: Field[Project | None] = model_field()
    title: Field[str] = model_field()
    notes: Field[str] = model_field()
    due_date: Field[datetime.date | None] = model_field()
    priority: Field[str] = model_field()
    is_complete: Field[bool] = model_field()
    tags: Field[list[Tag]] = model_field()

    def check(
        self, *, context: dict[str, Any] | None = None
    ) -> dict[str, list[str]] | None:
        if self.is_complete and self.due_date and self.due_date > datetime.date.today():
            return {"due_date": ["A completed task can't have a future due date."]}
        return None
