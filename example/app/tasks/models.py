from __future__ import annotations

from app.users.models import User
from plain import postgres
from plain.postgres import types
from plain.urls import reverse

PRIORITY_CHOICES = [
    ("low", "Low"),
    ("med", "Medium"),
    ("high", "High"),
    ("urg", "Urgent"),
]


@postgres.register_model
class Project(postgres.Model):
    owner: User = types.ForeignKeyField(
        User,
        on_delete=postgres.CASCADE,
        related_query_name="projects",
    )
    name = types.TextField(max_length=100)
    created_at = types.DateTimeField(create_now=True)

    query: postgres.QuerySet[Project] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["name"],
        constraints=[
            postgres.UniqueConstraint(
                fields=["owner", "name"], name="tasks_project_owner_name_unique"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name


@postgres.register_model
class Tag(postgres.Model):
    owner: User = types.ForeignKeyField(
        User,
        on_delete=postgres.CASCADE,
        related_query_name="tags",
    )
    name = types.TextField(max_length=40)

    query: postgres.QuerySet[Tag] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["name"],
        constraints=[
            postgres.UniqueConstraint(
                fields=["owner", "name"], name="tasks_tag_owner_name_unique"
            ),
        ],
    )

    def __str__(self) -> str:
        return self.name


@postgres.register_model
class TaskTag(postgres.Model):
    """Through model for Task ↔ Tag M2M."""

    task: Task = types.ForeignKeyField("Task", on_delete=postgres.CASCADE)
    task_id: int
    tag: Tag = types.ForeignKeyField(Tag, on_delete=postgres.CASCADE)
    tag_id: int

    query: postgres.QuerySet[TaskTag] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["task", "tag"], name="tasks_tasktag_task_tag_unique"
            ),
        ],
    )


@postgres.register_model
class Task(postgres.Model):
    owner: User = types.ForeignKeyField(
        User,
        on_delete=postgres.CASCADE,
        related_query_name="tasks",
    )
    project: Project | None = types.ForeignKeyField(
        Project,
        on_delete=postgres.SET_NULL,
        related_query_name="tasks",
        allow_null=True,
        required=False,
    )
    title = types.TextField(max_length=200)
    notes = types.TextField(default="", required=False)
    due_date = types.DateField(allow_null=True, required=False)
    priority = types.TextField(max_length=4, choices=PRIORITY_CHOICES, default="med")
    is_complete = types.BooleanField(default=False)
    tags: types.ManyToManyManager[Tag] = types.ManyToManyField(Tag, through=TaskTag)
    created_at = types.DateTimeField(create_now=True)
    updated_at = types.DateTimeField(create_now=True, update_now=True)

    query: postgres.QuerySet[Task] = postgres.QuerySet()

    model_options = postgres.Options(
        ordering=["is_complete", "-created_at"],
        indexes=[
            postgres.Index(
                name="tasks_task_owner_complete_idx",
                fields=["owner", "is_complete", "-created_at"],
            ),
            postgres.Index(
                name="tasks_task_project_idx",
                fields=["project"],
            ),
        ],
    )

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("tasks:detail", id=self.id)
