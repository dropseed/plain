from __future__ import annotations

from plain.api import openapi
from plain.api.views import APIView
from plain.auth import get_request_user
from plain.auth.views import LoginRequired
from plain.schema import Invalid
from plain.urls import Router, path

from .forms import TaskForm
from .models import Task
from .schemas import TaskQuickAddSchema

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
        form = TaskForm(request=self.request, owner=user)
        if not form.is_valid():
            return 400, {"errors": form.errors}
        form.instance.owner = user
        task = form.save()
        return 201, _serialize(task)


class TaskQuickAddAPIView(APIView):
    """Schema-based parallel to TaskListAPIView.post.

    Same job (create a task from JSON), but uses plain.schema.Schema instead
    of plain.forms.ModelForm. Validation is a pure function call — no
    request kwarg, no .is_valid() / .cleaned_data dance — and the result
    is type-narrowed so result.data attributes are statically typed.
    """

    @openapi.schema(
        {
            "summary": "Quick-add a task from a JSON body using a Schema.",
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

        # result.data is statically typed as TaskQuickAddSchema here.
        # An agent that mistypes a field name gets caught at type-check time.
        task = Task.query.create(
            owner=user,
            title=result.data.title,
            notes=result.data.notes,
            priority=result.data.priority or "med",
            is_complete=result.data.is_complete,
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
