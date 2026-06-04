"""Smoke tests for the example app's form views.

Drives notes / contacts / tasks end-to-end through `plain.test.Client` to
confirm the rebuilt `plain.forms` API (validate → field_value/field_errors
helpers → save) holds together across a plain Form, a ModelForm, an
FK/M2M ModelForm, and HTMX.
"""

from __future__ import annotations

import pytest
from app.contacts.models import ContactSubmission
from app.notes.models import Note
from app.tasks.models import Project, Tag, Task
from app.users.models import User

from plain.test import Client


@pytest.fixture
def user(db) -> User:
    return User.query.create(email="u@example.com", password="strongpass1")


@pytest.fixture
def client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


class TestNotes:
    def test_create_page_renders_the_form(self, client):
        response = client.get("/notes/new")
        assert response.status_code == 200
        assert 'name="title"' in response.content.decode()

    def test_valid_create_saves_and_redirects(self, client, user):
        response = client.post("/notes/new", data={"title": "First note", "body": "Hi"})
        assert response.status_code == 302
        note = Note.query.get(author=user, title="First note")
        assert note.body == "Hi"

    def test_invalid_create_re_renders_and_saves_nothing(self, client):
        response = client.post("/notes/new", data={"title": "", "body": "x"})
        assert response.status_code == 200
        assert not Note.query.exists()

    def test_update_page_is_prefilled(self, client, user):
        note = Note.query.create(author=user, title="Before", body="b")
        response = client.get(f"/notes/{note.id}/edit")
        assert response.status_code == 200
        assert 'value="Before"' in response.content.decode()

    def test_valid_update_persists(self, client, user):
        note = Note.query.create(author=user, title="Before", body="b")
        response = client.post(
            f"/notes/{note.id}/edit", data={"title": "After", "body": "b"}
        )
        assert response.status_code == 302
        assert Note.query.get(id=note.id).title == "After"

    def test_delete_removes_the_note(self, client, user):
        note = Note.query.create(author=user, title="Doomed", body="")
        response = client.post(f"/notes/{note.id}/delete")
        assert response.status_code == 302
        assert not Note.query.filter(id=note.id).exists()


class TestContacts:
    valid = {
        "name": "Dave",
        "email": "dave@example.com",
        "subject": "general",
        "message": "Hello there — this is a long enough message.",
    }

    def test_form_page_renders(self, client):
        response = client.get("/contacts")
        assert response.status_code == 200
        assert 'name="email"' in response.content.decode()

    def test_valid_submission_creates_a_record(self, client):
        response = client.post("/contacts", data=self.valid)
        assert response.status_code == 302
        assert ContactSubmission.query.filter(email="dave@example.com").exists()

    def test_check_rejects_a_blocked_email_domain(self, client):
        response = client.post(
            "/contacts", data={**self.valid, "email": "x@blocked.test"}
        )
        assert response.status_code == 200
        assert not ContactSubmission.query.exists()

    def test_company_field_is_conditional_on_the_query_param(self, client):
        assert 'name="company"' not in client.get("/contacts").content.decode()
        assert 'name="company"' in client.get("/contacts?company=1").content.decode()

    def test_archive_filters_by_query_params(self, client):
        ContactSubmission.query.create(
            name="A", email="a@x.com", subject="bug", message="needle in here"
        )
        ContactSubmission.query.create(
            name="B", email="b@x.com", subject="general", message="nothing"
        )
        response = client.get("/contacts/archive?search=needle")
        body = response.content.decode()
        assert response.status_code == 200
        assert "a@x.com" in body
        assert "b@x.com" not in body


class TestTasks:
    def test_valid_create_saves_with_owner(self, client, user):
        response = client.post(
            "/tasks/new", data={"title": "Ship it", "priority": "high"}
        )
        assert response.status_code == 302
        task = Task.query.get(owner=user, title="Ship it")
        assert task.priority == "high"

    def test_invalid_create_re_renders(self, client):
        response = client.post("/tasks/new", data={"title": "", "priority": "med"})
        assert response.status_code == 200
        assert not Task.query.exists()

    def test_update_scopes_project_and_tags_to_the_owner(self, client, user):
        project = Project.query.create(owner=user, name="Inbox")
        tag = Tag.query.create(owner=user, name="urgent")
        task = Task.query.create(owner=user, title="Old", priority="med")

        response = client.post(
            f"/tasks/{task.id}/edit",
            data={
                "title": "New",
                "priority": "low",
                "project": str(project.id),
                "tags": str(tag.id),
            },
        )
        assert response.status_code == 302
        task = Task.query.get(id=task.id)
        assert task.title == "New"
        assert task.project.id == project.id
        assert list(task.tags.query) == [tag]

    def test_htmx_inline_rename(self, client, user):
        task = Task.query.create(owner=user, title="Old title", priority="med")
        response = client.post(
            f"/tasks/{task.id}",
            data={"title": "Renamed"},
            headers={"HX-Request": "true", "Plain-HX-Action": "rename"},
        )
        assert response.status_code == 200
        assert Task.query.get(id=task.id).title == "Renamed"

    def test_delete_removes_the_task(self, client, user):
        task = Task.query.create(owner=user, title="Doomed", priority="med")
        response = client.post(f"/tasks/{task.id}/delete")
        assert response.status_code == 302
        assert not Task.query.filter(id=task.id).exists()
