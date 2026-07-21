"""Behavior contract — plain-admin list bulk actions.

Drives the ``Actions`` flow end-to-end through ``plain.test.Client``: the POST
carries ``action_name`` plus ``action_ids`` (comma-joined ids, or ``__all__``
for the whole filtered view), and ``perform_action`` receives the selected
objects as a queryset. Assertions are limited to what a user observes — the
redirect back to the list and the resulting database rows.
"""

from __future__ import annotations

import pytest
from app.users.models import User

from plain.test import Client

LIST_URL = "/admin/p/user"


@pytest.fixture
def admin_client(db) -> Client:
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    client.force_login(user)
    return client


def run_action(client: Client, action_ids: str):
    return client.post(
        LIST_URL,
        data={"action_name": "Make admin", "action_ids": action_ids},
    )


def test_selected_ids_only_touches_those_rows(admin_client):
    a = User.query.create(username="a")
    b = User.query.create(username="b")
    c = User.query.create(username="c")

    response = run_action(admin_client, f"{a.id},{c.id}")

    assert response.status_code == 302
    assert User.query.get(id=a.id).is_admin is True
    assert User.query.get(id=b.id).is_admin is False
    assert User.query.get(id=c.id).is_admin is True


def test_all_sentinel_touches_the_whole_filtered_view(admin_client):
    users = [User.query.create(username=f"u{i}") for i in range(5)]

    response = run_action(admin_client, "__all__")

    assert response.status_code == 302
    for user in users:
        assert User.query.get(id=user.id).is_admin is True


def test_all_sentinel_respects_the_active_search_filter(admin_client):
    keep = User.query.create(username="keep-me")
    other = User.query.create(username="other")

    # "__all__" means every object in the *current* view, so a search filter
    # narrows what the action can reach.
    response = admin_client.post(
        f"{LIST_URL}?search=keep",
        data={"action_name": "Make admin", "action_ids": "__all__"},
    )

    assert response.status_code == 302
    assert User.query.get(id=keep.id).is_admin is True
    assert User.query.get(id=other.id).is_admin is False


def test_action_survives_sorting_by_a_computed_field(admin_client):
    # Sorting by a non-column field pulls the list into memory for display, but
    # the action still needs a queryset — ordering must stay out of the action
    # path (regression: previously this handed perform_action a plain list and
    # `.update()` raised AttributeError).
    a = User.query.create(username="b")
    b = User.query.create(username="a")

    response = admin_client.post(
        f"{LIST_URL}?order_by=username_upper",
        data={"action_name": "Make admin", "action_ids": "__all__"},
    )

    assert response.status_code == 302
    assert User.query.get(id=a.id).is_admin is True
    assert User.query.get(id=b.id).is_admin is True


def test_malformed_id_is_ignored_not_fatal(admin_client):
    # A non-coercible id (stale hidden input, tampered/garbled POST) must be
    # dropped like any other unmatched id, not raise a 500.
    real = User.query.create(username="real")

    response = run_action(admin_client, f"{real.id},not-a-number")

    assert response.status_code == 302
    assert User.query.get(id=real.id).is_admin is True


def test_out_of_scope_id_is_ignored(admin_client):
    visible = User.query.create(username="visible")
    hidden = User.query.create(username="hidden")

    # `hidden` isn't in the filtered view, so its id can't be acted on even if
    # it rides along in the POST.
    response = admin_client.post(
        f"{LIST_URL}?search=visible",
        data={"action_name": "Make admin", "action_ids": f"{visible.id},{hidden.id}"},
    )

    assert response.status_code == 302
    assert User.query.get(id=visible.id).is_admin is True
    assert User.query.get(id=hidden.id).is_admin is False
