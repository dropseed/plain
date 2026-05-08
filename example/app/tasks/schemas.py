from __future__ import annotations

from plain.schema import Schema, types

from .models import PRIORITY_CHOICES


class TaskQuickAddSchema(Schema):
    """Scalar-only quick-add schema, exercised by both the JSON API and the
    HTMX inline-rename endpoint. Parallel to TaskForm/TaskTitleForm but pure
    data — no request, no rendering, no model save magic.
    """

    title: str = types.TextField(max_length=200, min_length=1)
    notes: str | None = types.TextField(required=False, max_length=2000, initial="")
    priority: str | None = types.ChoiceField(choices=PRIORITY_CHOICES, required=False)
    is_complete: bool = types.BooleanField(required=False)


class TaskTitleSchema(Schema):
    """Single-field schema for the HTMX inline-title rename action."""

    title: str = types.TextField(max_length=200, min_length=1)
