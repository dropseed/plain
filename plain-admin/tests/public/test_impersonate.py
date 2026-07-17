"""Security tests for admin user impersonation.

Impersonation lets an allowed user (by default, an admin) act as another
user. The guardrails that matter: only allowed users can start it, admins
can't be impersonated, and stopping restores the original user.
"""

from __future__ import annotations

from app.users.models import User

from plain.auth.requests import get_request_user
from plain.test import Client


def test_admin_can_impersonate_regular_user():
    admin = User.query.create(username="admin", is_admin=True)
    target = User.query.create(username="target", is_admin=False)

    client = Client()
    client.force_login(admin)

    started = client.get(f"/admin/impersonate/start/{target.id}")
    assert started.status_code == 302

    # Subsequent requests are now served as the target user.
    response = client.get("/whoami")
    assert get_request_user(response.request).id == target.id


def test_stopping_impersonation_restores_original_user():
    admin = User.query.create(username="admin", is_admin=True)
    target = User.query.create(username="target", is_admin=False)

    client = Client()
    client.force_login(admin)
    client.get(f"/admin/impersonate/start/{target.id}")
    assert get_request_user(client.get("/whoami").request).id == target.id

    stopped = client.get("/admin/impersonate/stop")
    assert stopped.status_code == 302

    # Back to acting as the admin.
    assert get_request_user(client.get("/whoami").request).id == admin.id


def test_non_admin_cannot_start_impersonation():
    regular = User.query.create(username="regular", is_admin=False)
    target = User.query.create(username="target", is_admin=False)

    client = Client()
    client.force_login(regular)

    started = client.get(f"/admin/impersonate/start/{target.id}")
    assert started.status_code == 403

    # The effective user is unchanged — no impersonation took hold.
    assert get_request_user(client.get("/whoami").request).id == regular.id


def test_admin_users_cannot_be_impersonated():
    admin = User.query.create(username="admin", is_admin=True)
    other_admin = User.query.create(username="other_admin", is_admin=True)

    client = Client()
    client.force_login(admin)

    # The start view sets the session marker, but the middleware refuses to
    # swap to an admin target and clears it.
    assert client.get(f"/admin/impersonate/start/{other_admin.id}").status_code == 302

    blocked = client.get("/whoami")
    assert blocked.status_code == 403

    # After the refusal the marker is cleared, so normal requests resume.
    assert get_request_user(client.get("/whoami").request).id == admin.id
