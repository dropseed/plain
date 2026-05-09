"""MCP server exposing the notes app workflow tools.

Auth is a hardcoded bearer token for local/demo use — see `.mcp.json` for
the header MCP clients need to send. Do NOT deploy this as-is; swap to
env-var-based token auth (see the `plain.mcp` README) before exposing
beyond localhost.

Auto-discovered by `plain.mcp` on startup. Mounted in `app/urls.py`.
"""

from __future__ import annotations

import datetime
import hmac
from functools import cached_property
from typing import Literal

from app.notes.models import Note
from app.users.models import User
from plain.mcp import MCPTool, MCPUnauthorized, MCPView
from plain.postgres import Q

# Hardcoded dev credentials — not secrets, but treat as such if you fork.
DEV_TOKEN = "local-dev-only"
DEV_USER_EMAIL = "test@example.com"


class NotesTool(MCPTool):
    """Base for notes tools — narrows `self.mcp` to `NotesMCP` and exposes
    `self.user` as the demo user the bearer token maps to.
    """

    mcp: NotesMCP

    @property
    def user(self) -> User:
        return self.mcp.user


class ListMyNotes(NotesTool):
    """List the caller's notes, most recent first.

    Args:
        limit: Maximum number of notes to return.
    """

    def __init__(self, limit: int = 20):
        self.limit = limit

    def run(self) -> list:
        notes = Note.query.filter(author=self.user).order_by("-created_at")[
            : self.limit
        ]
        return [
            {
                "id": n.id,
                "title": n.title,
                "created_at": n.created_at.isoformat(),
                "updated_at": n.updated_at.isoformat(),
            }
            for n in notes
        ]


class SearchMyNotes(NotesTool):
    """Search the caller's notes by title or body (case-insensitive).

    Args:
        query: Substring to match against title or body.
        limit: Maximum number of matches to return.
    """

    def __init__(self, query: str, limit: int = 20):
        self.query = query
        self.limit = limit

    def run(self) -> str:
        notes = Note.query.filter(
            Q(author=self.user)
            & (Q(title__icontains=self.query) | Q(body__icontains=self.query))
        ).order_by("-created_at")[: self.limit]
        return "\n".join(f"{n.id}: {n.title}" for n in notes) or "No matches"


class GetMyNote(NotesTool):
    """Return the full body of one of the caller's notes.

    Args:
        note_id: ID of the note to retrieve.
    """

    def __init__(self, note_id: int):
        self.note_id = note_id

    def run(self) -> str | dict:
        note = Note.query.filter(author=self.user, id=self.note_id).first()
        if note is None:
            return f"No note {self.note_id} owned by this user."
        return {
            "id": note.id,
            "title": note.title,
            "body": note.body,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }


class CreateNote(NotesTool):
    """Create a new note owned by the caller.

    Args:
        title: Note title.
        body: Optional note body.
    """

    def __init__(self, title: str, body: str = ""):
        self.title = title
        self.body = body

    def run(self) -> str:
        note = Note(author=self.user, title=self.title, body=self.body)
        note.save()
        return f"Created note {note.id}: {note.title}"


class UpdateNote(NotesTool):
    """Update the title and/or body of one of the caller's notes.

    Args:
        note_id: ID of the note to update.
        title: New title, or leave empty to keep the existing one.
        body: New body, or leave empty to keep the existing one.
    """

    def __init__(self, note_id: int, title: str | None = None, body: str | None = None):
        self.note_id = note_id
        self.title = title
        self.body = body

    def run(self) -> str:
        note = Note.query.filter(author=self.user, id=self.note_id).first()
        if note is None:
            return f"No note {self.note_id} owned by this user."
        if self.title is not None:
            note.title = self.title
        if self.body is not None:
            note.body = self.body
        note.save()
        return f"Updated note {note.id}"


class DeleteNote(NotesTool):
    """Delete one of the caller's notes.

    Args:
        note_id: ID of the note to delete.
    """

    def __init__(self, note_id: int):
        self.note_id = note_id

    def run(self) -> str:
        note = Note.query.filter(author=self.user, id=self.note_id).first()
        if note is None:
            return f"No note {self.note_id} owned by this user."
        title = note.title
        note.delete()
        return f"Deleted note {self.note_id}: {title}"


class CountMyNotesByAge(NotesTool):
    """Count the caller's notes in a time bucket.

    Args:
        bucket: `recent` = last 7 days, `older` = everything else, `all` = total.
    """

    def __init__(self, bucket: Literal["all", "recent", "older"] = "all"):
        self.bucket = bucket

    def run(self) -> str:
        qs = Note.query.filter(author=self.user)
        if self.bucket != "all":
            cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=7)
            qs = (
                qs.filter(created_at__gte=cutoff)
                if self.bucket == "recent"
                else qs.filter(created_at__lt=cutoff)
            )
        return str(qs.count())


class WhoAmI(NotesTool):
    """Return the calling user's email."""

    def run(self) -> str:
        return self.user.email


class NotesMCP(MCPView):
    name = "plain-example"
    tools = [
        ListMyNotes,
        SearchMyNotes,
        GetMyNote,
        CreateNote,
        UpdateNote,
        DeleteNote,
        CountMyNotesByAge,
        WhoAmI,
    ]

    def before_request(self) -> None:
        header = self.request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise MCPUnauthorized("Missing Authorization header")
        if not hmac.compare_digest(header.removeprefix("Bearer "), DEV_TOKEN):
            raise MCPUnauthorized("Invalid token")

    @cached_property
    def user(self) -> User:
        return User.query.get(email=DEV_USER_EMAIL)
