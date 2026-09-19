"""Behavior baseline — the admin list's column sort control.

Each sortable column cycles unsorted -> ascending -> descending ->
cleared. The view works the cycle out per column (`get_column_headers`)
and the template renders it, so these assertions read the rendered page:
the link's destination, its `aria-label`, and the column's `aria-sort`.
"""

from __future__ import annotations

import pytest
from app.users.models import User
from plain.admin.views.objects import get_column_headers
from plain.test import Client

LIST_URL = "/admin/p/user"


@pytest.fixture
def admin_client(db) -> Client:
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    client.force_login(user)
    return client


class TestRenderedHeaders:
    def test_unsorted_column_links_to_ascending(self, admin_client):
        html = admin_client.get(LIST_URL).content.decode()

        assert "?page=1&amp;order_by=username" in html
        assert 'aria-label="Sort by Username ascending"' in html
        assert 'aria-sort="none"' in html

    def test_ascending_column_links_to_descending(self, admin_client):
        html = admin_client.get(f"{LIST_URL}?order_by=username").content.decode()

        assert "?page=1&amp;order_by=-username" in html
        assert 'aria-label="Sort by Username descending"' in html
        assert 'aria-sort="ascending"' in html

    def test_descending_column_links_to_cleared(self, admin_client):
        html = admin_client.get(f"{LIST_URL}?order_by=-username").content.decode()

        assert "?page=1&amp;order_by=" in html
        assert 'aria-label="Stop sorting by Username"' in html
        assert 'aria-sort="descending"' in html

    def test_other_columns_stay_unsorted(self, admin_client):
        html = admin_client.get(f"{LIST_URL}?order_by=username").content.decode()

        assert 'aria-label="Sort by ID ascending"' in html
        assert 'aria-sort="none"' in html

    def test_sorting_actually_orders_the_rows(self, admin_client):
        User.query.create(username="zzz")
        User.query.create(username="aaa")

        ascending = admin_client.get(f"{LIST_URL}?order_by=username").content.decode()
        descending = admin_client.get(f"{LIST_URL}?order_by=-username").content.decode()

        assert ascending.index("aaa") < ascending.index("zzz")
        assert descending.index("zzz") < descending.index("aaa")


class TestColumnHeaders:
    """The cycle itself, without a request in the way."""

    def test_unsorted(self):
        (header,) = get_column_headers(
            ("username",), order_by_field="", order_by_direction=""
        )
        assert header.label == "Username"
        assert header.aria_sort == "none"
        assert header.sort_url == "?page=1&order_by=username"
        assert not header.sorted_ascending
        assert not header.sorted_descending

    def test_ascending(self):
        (header,) = get_column_headers(
            ("username",), order_by_field="username", order_by_direction=""
        )
        assert header.aria_sort == "ascending"
        assert header.sort_url == "?page=1&order_by=-username"
        assert header.sorted_ascending

    def test_descending_clears(self):
        (header,) = get_column_headers(
            ("username",), order_by_field="username", order_by_direction="-"
        )
        assert header.aria_sort == "descending"
        assert header.sort_url == "?page=1&order_by="
        assert header.sorted_descending
        assert header.sort_label == "Stop sorting by Username"

    def test_a_sorted_column_does_not_affect_its_neighbors(self):
        first, second = get_column_headers(
            ("id", "username"), order_by_field="username", order_by_direction=""
        )
        assert first.aria_sort == "none"
        assert first.label == "ID"
        assert second.aria_sort == "ascending"
