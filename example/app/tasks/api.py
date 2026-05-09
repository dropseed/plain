from __future__ import annotations

from plain.api import openapi
from plain.api.views import APIView
from plain.auth import get_request_user
from plain.auth.views import LoginRequired
from plain.schema import Invalid
from plain.urls import Router, path

from .models import Task
from .schemas import TaskQuickAddSchema, TaskSchema

TASK_SCHEMA = {
    "type": "object",
    "required": ["id", "title", "is_complete"],
    "properties": {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "notes": {"type": "string"},
        "priority": {"type": "string"},
        "is_complete": {"type": "boolean"},
        "due_date": {"type": "string", "format": "date", "nullable": True},
    },
}


def _serialize(task: Task) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "notes": task.notes,
        "priority": task.priority,
        "is_complete": task.is_complete,
        "due_date": task.due_date.isoformat() if task.due_date else None,
    }


class TaskListAPIView(APIView):
    """plain.api view that uses the same ModelForm to validate JSON input."""

    @openapi.schema(
        {
            "summary": "List tasks for the current user.",
            "responses": {
                "200": {
                    "description": "A list of tasks.",
                    "content": openapi.json_content(
                        {
                            "type": "object",
                            "required": ["results"],
                            "properties": {
                                "results": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Task"},
                                }
                            },
                        }
                    ),
                }
            },
        }
    )
    def get(self) -> dict:
        user = get_request_user(self.request)
        if not user:
            raise LoginRequired(login_url=None)
        tasks = Task.query.filter(owner=user)[:50]
        return {"results": [_serialize(t) for t in tasks]}

    @openapi.schema(
        {
            "summary": "Create a task from a JSON body using TaskSchema.",
            "requestBody": openapi.schema_body(TaskSchema),
            "responses": {
                "201": {
                    "description": "The created task.",
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Task"}
                    ),
                },
                "400": {"description": "Validation errors."},
            },
        }
    )
    def post(self) -> tuple[int, dict]:
        user = get_request_user(self.request)
        if not user:
            raise LoginRequired(login_url=None)
        result = TaskSchema.validate(self.request.json_data)
        if isinstance(result, Invalid):
            return 400, {"errors": result.errors}

        relations = result.resolve_relations(owner=user)
        if isinstance(relations, Invalid):
            return 400, {"errors": relations.errors}

        task = Task()
        task.owner = user
        result.apply_to_task(task, project=relations["project"])
        task.save()
        if relations["tags"]:
            task.tags.set(relations["tags"])
        return 201, _serialize(task)


class TaskQuickAddAPIView(APIView):
    """Schema-based parallel to TaskListAPIView.post.

    Same job (create a task from JSON), but uses plain.schema.Schema instead
    of plain.forms.ModelForm. The same TaskQuickAddSchema class drives
    runtime validation AND the OpenAPI requestBody documentation — one
    declaration, two outputs.
    """

    @openapi.schema(
        {
            "summary": "Quick-add a task from a JSON body using a Schema.",
            "requestBody": openapi.schema_body(TaskQuickAddSchema),
            "responses": {
                "201": {
                    "description": "The created task.",
                    "content": openapi.json_content(
                        {"$ref": "#/components/schemas/Task"}
                    ),
                },
                "400": {"description": "Validation errors."},
            },
        }
    )
    def post(self) -> tuple[int, dict]:
        user = get_request_user(self.request)
        if not user:
            raise LoginRequired(login_url=None)

        result = TaskQuickAddSchema.validate(self.request.json_data)
        if isinstance(result, Invalid):
            return 400, {"errors": result.errors}

        # `result` IS the typed TaskQuickAddSchema instance after the Invalid
        # eliminate. An agent that mistypes a field name fails type-check.
        task = Task.query.create(
            owner=user,
            title=result.title,
            notes=result.notes,
            priority=result.priority or "med",
            is_complete=result.is_complete,
        )
        return 201, _serialize(task)


@openapi.schema(
    {
        "openapi": "3.0.3",
        "info": {"title": "Tasks API", "version": "1.0.0"},
    }
)
class TasksAPIRouter(Router):
    namespace = "tasks_api"
    openapi_components = {"schemas": {"Task": TASK_SCHEMA}}
    urls = [
        path("tasks/", TaskListAPIView, name="list"),
        path("tasks/quick/", TaskQuickAddAPIView, name="quick"),
    ]
