"""The SQL plain-admin's converted query sites emit, pinned statement by statement.

These sites moved off the string-form query API: the pinned-nav reads are
`select(PinnedNavItem.view_slug, flat=True)` where they were
`values_list("view_slug", flat=True)`, and the object lookups are
`where(model.id.equals(...))` / `where(model.id.is_in(...))` where they were
`get(id=...)` / `filter(id__in=...)`. The conversion is only correct if the
SQL is unchanged, so pin it: if a converted call starts selecting extra
columns, adding a join, or dropping a clause, these fail and you decide
whether it should have.
"""

from __future__ import annotations

import pytest
from app.users.models import User
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from plain.admin.models import PinnedNavItem
from plain.test import Client

LIST_URL = "/admin/p/user"
LIST_VIEW_SLUG = "app_users_admin_useradmin_listview"

PINNED_TABLE = '"plainadmin_pinnednavitem"'
USER_TABLE = '"users_user"'

# One column, no join. PinnedNavItem orders by ("order", "created_at"), so the
# ORDER BY is the model's default, not something a call site asked for.
PINNED_SLUGS = (
    'SELECT "plainadmin_pinnednavitem"."view_slug" '
    'FROM "plainadmin_pinnednavitem" '
    'WHERE "plainadmin_pinnednavitem"."user_id" = %s '
    'ORDER BY "plainadmin_pinnednavitem"."order" ASC, '
    '"plainadmin_pinnednavitem"."created_at" ASC'
)
NAV_TAB_SLUGS = f"{PINNED_SLUGS} LIMIT 6"
MAX_ORDER = (
    'SELECT "plainadmin_pinnednavitem"."order" '
    'FROM "plainadmin_pinnednavitem" '
    'WHERE "plainadmin_pinnednavitem"."user_id" = %s '
    'ORDER BY "plainadmin_pinnednavitem"."order" DESC LIMIT 1'
)
USER_BY_ID = (
    'SELECT "users_user"."id", "users_user"."is_admin", "users_user"."username" '
    'FROM "users_user" WHERE "users_user"."id" = %s LIMIT 21'
)
USERS_BY_ID_IN = (
    'UPDATE "users_user" SET "is_admin" = %s WHERE "users_user"."id" IN (%s, %s)'
)


@pytest.fixture
def admin_client(db) -> Client:
    user = User.query.create(username="admin", is_admin=True)
    client = Client()
    client.force_login(user)
    return client


def statements(otel_spans: InMemorySpanExporter, table: str) -> list[str]:
    """Every statement the captured spans carry that touches `table`, in order."""
    return [
        " ".join(str(span.attributes["db.query.text"]).split())
        for span in otel_spans.get_finished_spans()
        if span.attributes
        and "db.query.text" in span.attributes
        and table in str(span.attributes["db.query.text"])
    ]


def test_a_page_render_reads_only_the_pinned_view_slugs(admin_client, otel_spans):
    """registry.get_nav_tabs() and AdminView's template context, in that order."""
    otel_spans.clear()
    assert admin_client.get(LIST_URL).status_code == 200

    assert statements(otel_spans, PINNED_TABLE) == [NAV_TAB_SLUGS, PINNED_SLUGS]


def test_pinning_reads_only_the_order_column(admin_client, otel_spans):
    otel_spans.clear()
    response = admin_client.post("/admin/_/pin", data={"view_slug": LIST_VIEW_SLUG})
    assert response.status_code == 302

    sql = statements(otel_spans, PINNED_TABLE)
    assert len(sql) == 4
    assert sql[0].startswith('SELECT COUNT(*) AS "__count"')
    assert sql[1] == MAX_ORDER
    # The row itself is still a get_or_create(): SELECT, then INSERT.
    assert sql[2].startswith('SELECT "plainadmin_pinnednavitem"."id"')
    assert sql[3].startswith('INSERT INTO "plainadmin_pinnednavitem"')


def test_reordering_reads_only_the_pinned_view_slugs(admin_client, otel_spans):
    user = User.query.get(username="admin")
    PinnedNavItem.query.create(user=user, view_slug=LIST_VIEW_SLUG, order=0)

    otel_spans.clear()
    response = admin_client.post(
        "/admin/_/reorder", data={"slugs": f'["{LIST_VIEW_SLUG}"]'}
    )
    assert response.status_code == 200

    sql = statements(otel_spans, PINNED_TABLE)
    assert len(sql) == 2
    assert sql[0] == PINNED_SLUGS
    assert sql[1].startswith('UPDATE "plainadmin_pinnednavitem" SET "order" = %s')


def test_the_detail_view_looks_its_object_up_by_id(admin_client, otel_spans):
    user = User.query.create(username="subject")

    otel_spans.clear()
    assert admin_client.get(f"{LIST_URL}/{user.id}").status_code == 200

    # Two lookups with the same shape: the session resolving the logged-in
    # user, then AdminModelDetailView.get_object().
    assert statements(otel_spans, USER_TABLE) == [USER_BY_ID, USER_BY_ID]


def test_an_action_matches_the_selected_ids_with_in(admin_client, otel_spans):
    a = User.query.create(username="a")
    b = User.query.create(username="b")

    otel_spans.clear()
    response = admin_client.post(
        LIST_URL,
        data={"action_name": "Make admin", "action_ids": f"{a.id},{b.id}"},
    )
    assert response.status_code == 302

    # select_objects_by_id() keeps the queryset lazy, so the IN lands on the
    # UPDATE the action performs.
    assert statements(otel_spans, USER_TABLE) == [USER_BY_ID, USERS_BY_ID_IN]
