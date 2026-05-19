from __future__ import annotations

import datetime

from app.users.models import User
from plain.forms import Error, Form, types
from plain.postgres.forms import ModelForm, model_field

from .models import Project, Tag, Task


class TaskForm(ModelForm):
    """A ModelForm over Task — exercises an FK (`project`), an M2M (`tags`),
    plus date, choice, and boolean fields, and a cross-field `check()`.

    `owner` is not a form field; the view passes it to `create_from()`. Use
    `TaskForm.for_owner(user)` to get a copy whose `project`/`tags` choices
    are scoped to that user's rows.
    """

    project = model_field(Task.project)
    title = model_field(Task.title)
    notes = model_field(Task.notes)
    due_date = model_field(Task.due_date)
    priority = model_field(Task.priority)
    is_complete = model_field(Task.is_complete)
    tags = model_field(Task.tags)

    @classmethod
    def for_owner(cls, owner: User) -> type[TaskForm]:
        """A TaskForm whose `project`/`tags` choices are scoped to one owner."""
        return cls.with_querysets(
            project=Project.query.filter(owner=owner),
            tags=Tag.query.filter(owner=owner),
        )

    def check(self) -> list[Error] | None:
        if self.is_complete and self.due_date and self.due_date > datetime.date.today():
            return [
                Error(
                    "A task that's already complete can't have a future due date.",
                    code="future_due_date",
                    field="due_date",
                )
            ]
        return None


class TaskTitleForm(Form):
    """The single-field form behind the HTMX inline-title edit."""

    title = types.TextField(max_length=200, min_length=1)
