from __future__ import annotations

import datetime
from typing import Any

from app.users.models import User
from plain import forms
from plain.postgres.forms import ModelForm, ModelMultipleChoiceField

from .models import Project, Tag, Task


class TaskForm(ModelForm):
    """ModelForm exercising FK, M2M, date, choice, and boolean fields plus
    cross-field clean(). Owner is excluded — set on the instance before save.
    """

    class Meta:
        model = Task
        fields = (
            "project",
            "title",
            "notes",
            "due_date",
            "priority",
            "is_complete",
            "tags",
        )

    def __init__(self, *, owner: User, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # FK auto-builds as ModelChoiceField with an unscoped queryset — narrow it.
        self.fields["project"].queryset = Project.query.filter(owner=owner)  # ty: ignore[unresolved-attribute]
        # M2M doesn't auto-build (modelfield_to_formfield returns None for non-ColumnField),
        # so construct the field by hand. Meta.fields still lists "tags" so save_m2m runs.
        self.fields["tags"] = ModelMultipleChoiceField(
            queryset=Tag.query.filter(owner=owner),
            required=False,
        )

    def clean(self) -> dict[str, Any]:
        cleaned = super().clean()
        is_complete = cleaned.get("is_complete")
        due_date = cleaned.get("due_date")
        if is_complete and due_date and due_date > datetime.date.today():
            raise forms.ValidationError(
                "A task that's already complete can't have a future due date."
            )
        return cleaned


class TaskTitleForm(forms.Form):
    """Single-field form used by the HTMX inline-title edit."""

    title = forms.TextField(max_length=200, min_length=1)
