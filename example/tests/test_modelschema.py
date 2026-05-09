"""ModelSchema smoke tests against the example tasks app's Task model.

Exercises auto-derive of scalar/FK/M2M fields, queryset substitution
via context, and the save(instance=None) method.
"""

from __future__ import annotations

import datetime

import pytest
from app.tasks.models import PRIORITY_CHOICES, Project, Tag, Task
from app.users.models import User

from plain.postgres.modelschema import (
    Invalid,
    ModelChoiceField,
    ModelMultipleChoiceField,
    ModelSchema,
)


@pytest.fixture
def user(db):
    return User.query.create(email="t@x.test", password="strong-pw-1")


@pytest.fixture
def project(user):
    return Project.query.create(owner=user, name="Inbox")


@pytest.fixture
def tag(user):
    return Tag.query.create(owner=user, name="t1")


class TaskSchema(ModelSchema):
    model = Task

    title: str
    notes: str
    priority: str
    is_complete: bool
    due_date: datetime.date | None
    project: Project | None
    tags: list[Tag]


def test_modelschema_autoderive_field_types():
    """Field instance types match what the model would expect."""
    fields = TaskSchema._schema_fields
    assert {
        "title",
        "notes",
        "priority",
        "is_complete",
        "due_date",
        "project",
        "tags",
    } == set(fields)

    # priority is a TextField with choices on the model — should be
    # TypedChoiceField on the schema.
    from plain.forms.fields import (
        BooleanField,
        DateField,
        TextField,
        TypedChoiceField,
    )

    assert isinstance(fields["title"], TextField)
    assert isinstance(fields["notes"], TextField)
    assert isinstance(fields["priority"], TypedChoiceField)
    # priority field's choices include the PRIORITY_CHOICES values
    choices_values = [v for v, _ in fields["priority"].choices]
    for value, _label in PRIORITY_CHOICES:
        assert value in choices_values
    assert isinstance(fields["is_complete"], BooleanField)
    assert isinstance(fields["due_date"], DateField)
    assert isinstance(fields["project"], ModelChoiceField)
    assert isinstance(fields["tags"], ModelMultipleChoiceField)


def test_modelschema_validates_basic_input(db, project):
    result = TaskSchema.validate(
        {
            "title": "T1",
            "notes": "n",
            "priority": "low",
            "is_complete": False,
            "due_date": "2026-01-01",
            "project": str(project.id),
            "tags": [],
        }
    )
    assert not isinstance(result, Invalid)
    assert result.title == "T1"
    assert result.priority == "low"
    # ModelChoiceField resolves the FK ID to the model instance.
    assert result.project == project


def test_modelschema_invalid_fk_id(db):
    result = TaskSchema.validate(
        {
            "title": "T1",
            "notes": "",
            "priority": "low",
            "is_complete": False,
            "project": "999999",
            "tags": [],
        }
    )
    assert isinstance(result, Invalid)
    assert "project" in result.errors


def test_modelschema_queryset_substitution_via_context(db, user, project):
    """Per-request queryset substitution scopes FK/M2M to owner."""
    other = User.query.create(email="other@x.test", password="strong-pw-2")
    other_project = Project.query.create(owner=other, name="Their inbox")

    # Without scoping, both projects are valid (default is Project.query).
    result = TaskSchema.validate(
        {
            "title": "T",
            "notes": "",
            "priority": "low",
            "is_complete": False,
            "project": str(other_project.id),
            "tags": [],
        }
    )
    assert not isinstance(result, Invalid)

    # With owner-scoped queryset in context, the other-user's project fails.
    result = TaskSchema.validate(
        {
            "title": "T",
            "notes": "",
            "priority": "low",
            "is_complete": False,
            "project": str(other_project.id),
            "tags": [],
        },
        context={
            "querysets": {
                "project": Project.query.filter(owner=user),
            },
        },
    )
    assert isinstance(result, Invalid)
    assert "project" in result.errors


def test_modelschema_save_creates_instance_with_m2m(db, user, project, tag):
    result = TaskSchema.validate(
        {
            "title": "Saved",
            "notes": "",
            "priority": "low",
            "is_complete": False,
            "project": str(project.id),
            "tags": [str(tag.id)],
        }
    )
    assert not isinstance(result, Invalid)

    task = Task(owner=user)
    saved = result.save(task)
    assert saved.id is not None
    assert saved.title == "Saved"
    assert saved.project == project
    assert list(saved.tags.query) == [tag]


def test_modelschema_save_with_existing_instance_clears_m2m_when_empty(
    db, user, project, tag
):
    """Saving with empty tags should clear M2M (existing tags removed)."""
    task = Task.query.create(owner=user, title="orig", priority="low")
    task.tags.set([tag])
    assert list(task.tags.query) == [tag]

    result = TaskSchema.validate(
        {
            "title": "edited",
            "notes": "",
            "priority": "low",
            "is_complete": False,
            "project": str(project.id),
            "tags": [],
        }
    )
    assert not isinstance(result, Invalid)
    result.save(task)
    task.refresh_from_db()
    assert list(task.tags.query) == []
    assert task.title == "edited"


def test_modelschema_save_with_no_instance_creates_fresh(db, user, project):
    """save() without an instance constructs one from `model = X` and saves."""

    class NoOwnerSchema(ModelSchema):
        model = Task

        title: str
        priority: str
        is_complete: bool

    result = NoOwnerSchema.validate(
        {"title": "Fresh", "priority": "low", "is_complete": False}
    )
    assert not isinstance(result, Invalid)
    # Task requires owner — assigning before save() works because save()
    # also calls instance.save() which triggers the owner check.
    instance = Task(owner=user)
    saved = result.save(instance)
    assert saved.id is not None
    assert saved.title == "Fresh"
