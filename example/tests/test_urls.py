from app.contacts.models import ContactSubmission
from app.tasks.models import Project, Tag, Task
from app.users.models import User

from plain.test import Client


def test_admin_access(db):
    client = Client()

    # Login required
    assert client.get("/admin").status_code == 302

    user = User.query.create(email="admin@example.com", password="strongpass1")
    client.force_login(user)

    # Not admin yet
    assert client.get("/admin").status_code == 404

    user.is_admin = True
    user.save()

    # Now admin
    assert client.get("/admin").status_code in {200, 302}


def test_contact_schema_page_renders(db):
    response = Client().get("/contacts/schema")
    assert response.status_code == 200
    assert "Contact us" in response.content.decode()


def test_contact_schema_valid_submission(db):
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "Ada",
            "email": "ada@example.com",
            "subject": "general",
            "message": "This is a long enough message.",
        },
    )
    assert response.status_code == 302
    assert response.headers["Location"] == "/contacts/schema/success"
    assert ContactSubmission.query.filter(email="ada@example.com").exists()


def test_contact_schema_invalid_rerenders(db):
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "A",  # below min_length
            "email": "not-an-email",
            "subject": "general",
            "message": "short",  # below min_length
        },
    )
    assert response.status_code == 200
    assert "field-error" in response.content.decode()
    assert ContactSubmission.query.count() == 0


def test_contact_schema_check_runs(db):
    # check() cross-field rule: a bug report needs 30+ characters.
    response = Client().post(
        "/contacts/schema",
        data={
            "name": "Ada",
            "email": "ada@example.com",
            "subject": "bug",
            "message": "Too short for a bug.",
        },
    )
    assert response.status_code == 200
    assert "at least 30 characters" in response.content.decode()
    assert ContactSubmission.query.count() == 0


def test_task_schema_create_page_renders(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    client.force_login(user)
    response = client.get("/tasks/schema/new")
    assert response.status_code == 200
    assert "New task" in response.content.decode()


def test_task_schema_create_with_fk_and_m2m(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    client.force_login(user)
    project = Project.query.create(owner=user, name="Inbox")
    urgent = Tag.query.create(owner=user, name="urgent")
    later = Tag.query.create(owner=user, name="later")

    response = client.post(
        "/tasks/schema/new",
        data={
            "title": "Write the docs",
            "project": str(project.id),
            "priority": "high",
            "tags": [str(urgent.id), str(later.id)],
        },
    )
    assert response.status_code == 302
    task = Task.query.filter(owner=user, title="Write the docs").first()
    assert task is not None
    assert task.project == project
    assert {tag.name for tag in task.tags.query} == {"urgent", "later"}


def test_task_schema_create_scopes_relations_to_owner(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    other = User.query.create(email="other@example.com", password="strongpass1")
    client.force_login(user)
    # A project owned by someone else must not be selectable.
    other_project = Project.query.create(owner=other, name="Secret")

    response = client.post(
        "/tasks/schema/new",
        data={"title": "Sneaky", "project": str(other_project.id)},
    )
    assert response.status_code == 200
    assert "field-error" in response.content.decode()
    assert Task.query.filter(title="Sneaky").count() == 0


def test_task_schema_update_prefills_and_saves(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    client.force_login(user)
    inbox = Project.query.create(owner=user, name="Inbox")
    side = Project.query.create(owner=user, name="Side")
    urgent = Tag.query.create(owner=user, name="urgent")
    task = Task.query.create(owner=user, title="Old title", project=inbox)
    task.tags.set([urgent])

    # GET pre-fills the form from the task via ModelSchema.initial_from().
    page = client.get(f"/tasks/schema/{task.id}/edit")
    assert page.status_code == 200
    assert "Old title" in page.content.decode()

    # POST applies the validated values back; omitting `tags` clears the M2M.
    response = client.post(
        f"/tasks/schema/{task.id}/edit",
        data={"title": "New title", "project": str(side.id), "priority": "high"},
    )
    assert response.status_code == 302
    task = Task.query.get(id=task.id)
    assert task.title == "New title"
    assert task.project == side
    assert task.tags.query.count() == 0


def test_task_schema_update_404_for_another_owner(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    other = User.query.create(email="other@example.com", password="strongpass1")
    client.force_login(user)
    others_task = Task.query.create(owner=other, title="Not yours")
    assert client.get(f"/tasks/schema/{others_task.id}/edit").status_code == 404


def test_task_api_create_from_json(db):
    """The JSON-body counterpart to the form views: TaskSchema parses
    request.json_data directly, scoped to the current user."""
    client = Client()
    user = User.query.create(email="api@example.com", password="strongpass1")
    client.force_login(user)
    project = Project.query.create(owner=user, name="Inbox")
    urgent = Tag.query.create(owner=user, name="urgent")

    response = client.post(
        "/tasks-api/tasks",
        data={
            "title": "Ship the API",
            "project": project.id,
            "priority": "high",
            "tags": [urgent.id],
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    task = Task.query.filter(owner=user, title="Ship the API").first()
    assert task is not None
    assert task.project == project
    assert {tag.name for tag in task.tags.query} == {"urgent"}


def test_task_api_create_json_validation_errors(db):
    """Invalid JSON comes back as a 400 with per-field errors — no task saved."""
    client = Client()
    user = User.query.create(email="api@example.com", password="strongpass1")
    client.force_login(user)

    response = client.post(
        "/tasks-api/tasks",
        data={"title": ""},  # required field empty
        content_type="application/json",
    )
    assert response.status_code == 400
    assert "title" in response.json()["errors"]
    assert Task.query.count() == 0


def test_task_schema_delete(db):
    client = Client()
    user = User.query.create(email="tasker@example.com", password="strongpass1")
    client.force_login(user)
    task = Task.query.create(owner=user, title="Doomed")

    page = client.get(f"/tasks/schema/{task.id}/delete")
    assert page.status_code == 200
    assert "Doomed" in page.content.decode()

    response = client.post(f"/tasks/schema/{task.id}/delete")
    assert response.status_code == 302
    assert Task.query.filter(id=task.id).count() == 0
