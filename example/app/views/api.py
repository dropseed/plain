from __future__ import annotations

import re

from app.notes.models import Note
from plain.api import openapi
from plain.api.views import APIView
from plain.http import NotFoundError404
from plain.urls import Router, path

NOTE_SCHEMA = {
    "type": "object",
    "required": ["id", "title", "body", "created_at", "updated_at"],
    "properties": {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "body": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}


def _serialize(note: Note) -> dict:
    return {
        "id": note.id,
        "title": note.title,
        "body": note.body,
        "created_at": note.created_at.isoformat(),
        "updated_at": note.updated_at.isoformat(),
    }


@openapi.schema(
    {
        "responses": {
            "200": {
                "description": "A page of notes.",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["results"],
                            "properties": {
                                "results": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/Note"},
                                }
                            },
                        }
                    }
                },
            }
        }
    }
)
class NoteListAPIView(APIView):
    def get(self):
        notes = Note.query.all()[:25]
        return {"results": [_serialize(n) for n in notes]}


@openapi.schema(
    {
        "responses": {
            "200": {
                "description": "A single note.",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/Note"},
                    }
                },
            },
            "404": {"description": "Note not found."},
        }
    }
)
class NoteDetailAPIView(APIView):
    def get(self):
        note = Note.query.filter(id=self.url_kwargs["id"]).first()
        if note is None:
            raise NotFoundError404
        return _serialize(note)


class NotFoundAPIView(APIView):
    """Catch-all for unmatched /api/ paths so we return JSON 404s.

    URL resolution failures escape to the framework's global
    `response_for_exception`, which renders `404.html`. Routing every
    unmatched path through an `APIView` lets `handle_exception` emit JSON
    instead.
    """

    def get(self):
        raise NotFoundError404

    def post(self):
        raise NotFoundError404

    def put(self):
        raise NotFoundError404

    def patch(self):
        raise NotFoundError404

    def delete(self):
        raise NotFoundError404


@openapi.schema(
    {
        "openapi": "3.0.3",
        "info": {
            "title": "Example API",
            "version": "1.0.0",
            "description": "Example API surface used for OpenAPI conformance testing.",
        },
    }
)
class APIRouter(Router):
    namespace = "api"
    openapi_components = {"schemas": {"Note": NOTE_SCHEMA}}
    urls = [
        path("notes/", NoteListAPIView, name="notes_list"),
        path("notes/<int:id>/", NoteDetailAPIView, name="notes_detail"),
        # `[\s\S]` (vs the `path` converter's `.+`) matches control
        # characters too, so newline-bearing paths still hit an APIView.
        path(re.compile(r"^[\s\S]+$"), NotFoundAPIView, name="not_found"),
    ]
