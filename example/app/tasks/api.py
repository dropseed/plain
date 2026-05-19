from __future__ import annotations

from plain.api import openapi
from plain.api.views import APIView
from plain.auth import get_request_user
from plain.auth.views import LoginRequired
from plain.postgres.forms import create_from
from plain.urls import Router, path

from .forms import TaskForm
from .models import Task

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
            "summary": "Create a task from a JSON body using TaskForm.",
            "requestBody": openapi.json_body(
                {"$ref": "#/components/schemas/Task"},
            ),
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
        result = TaskForm.for_owner(user).validate(self.request.json_data)
        if not result:
            return 400, {
                "errors": [
                    {"field": e.field, "code": e.code, "message": e.message}
                    for e in result.errors
                ]
            }
        # `owner` isn't a form field — pass it to create_from() as an extra.
        task = create_from(Task, result, owner=user)
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
    ]
