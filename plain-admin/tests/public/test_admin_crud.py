"""Behavior regression baseline — plain-admin object CRUD.

Drives the admin list / detail / create / update / delete views end-to-end
through ``plain.test.Client`` against a full-CRUD ``AdminViewset`` registered
for the test app's ``User`` model (see ``app/users/admin.py``). Assertions are
limited to what a browser observes — HTTP status, redirect targets, rendered
page content, and database rows.
"""

from __future__ import annotations

from app.users.models import User
from helpers import make_admin_client

from plain.test import Client

LIST_URL = "/admin/p/user"
CREATE_URL = "/admin/p/user/create"


def detail_url(user: User) -> str:
    return f"/admin/p/user/{user.id}"


def edit_url(user: User) -> str:
    return f"/admin/p/user/{user.id}/edit"


def delete_url(user: User) -> str:
    return f"/admin/p/user/{user.id}/delete"


class TestListAndDetail:
    def test_list_loads(self):
        admin_client = make_admin_client()
        User.query.create(username="list-probe")

        response = admin_client.get(LIST_URL)

        assert response.status_code == 200
        assert "list-probe" in response.content.decode()

    def test_detail_loads(self):
        admin_client = make_admin_client()
        user = User.query.create(username="detail-probe")

        response = admin_client.get(detail_url(user))

        assert response.status_code == 200
        assert "detail-probe" in response.content.decode()


class TestCreate:
    def test_create_page_loads(self):
        admin_client = make_admin_client()
        response = admin_client.get(CREATE_URL)

        assert response.status_code == 200
        assert 'name="username"' in response.content.decode()

    def test_valid_post_creates_object_and_redirects(self):
        admin_client = make_admin_client()
        assert not User.query.filter(username="created-user").exists()

        response = admin_client.post(CREATE_URL, form_data={"username": "created-user"})

        assert response.status_code == 302
        created = User.query.get(username="created-user")
        assert created.is_admin is False

    def test_invalid_post_shows_errors_and_creates_nothing(self):
        admin_client = make_admin_client()
        before = User.query.count()

        # username is required — a blank value must be rejected.
        response = admin_client.post(CREATE_URL, form_data={"username": ""})

        assert response.status_code == 200
        assert 'aria-invalid="true"' in response.content.decode()
        assert User.query.count() == before


class TestUpdate:
    def test_update_page_loads_prefilled(self):
        admin_client = make_admin_client()
        user = User.query.create(username="before-edit")

        response = admin_client.get(edit_url(user))

        assert response.status_code == 200
        assert 'value="before-edit"' in response.content.decode()

    def test_valid_post_persists_changes(self):
        admin_client = make_admin_client()
        user = User.query.create(username="before")

        response = admin_client.post(edit_url(user), form_data={"username": "after"})

        assert response.status_code == 302
        assert User.query.filter(id=user.id, username="after").exists()

    def test_invalid_post_leaves_object_unchanged(self):
        admin_client = make_admin_client()
        user = User.query.create(username="keep")

        response = admin_client.post(edit_url(user), form_data={"username": ""})

        assert response.status_code == 200
        assert 'aria-invalid="true"' in response.content.decode()
        assert User.query.filter(id=user.id, username="keep").exists()


class TestDelete:
    def test_delete_confirm_loads(self):
        admin_client = make_admin_client()
        user = User.query.create(username="to-delete")

        response = admin_client.get(delete_url(user))

        assert response.status_code == 200

    def test_delete_post_removes_object_and_redirects(self):
        admin_client = make_admin_client()
        user = User.query.create(username="delete-me")
        user_id = user.id

        response = admin_client.post(delete_url(user))

        assert response.status_code == 302
        assert not User.query.filter(id=user_id).exists()


class TestAccessControl:
    def test_crud_pages_require_login(self):
        """An anonymous visitor is redirected away from every CRUD page."""
        user = User.query.create(username="gated")
        client = Client()

        for url in (
            LIST_URL,
            CREATE_URL,
            detail_url(user),
            edit_url(user),
            delete_url(user),
        ):
            assert client.get(url).status_code == 302, url
