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

from admin_test_helpers import make_admin_client
from app.users.models import User
from plain.admin.models import PinnedNavItem
from plain.postgres.test import span_sql_statements
from plain.test import capture_spans

LIST_URL = "/admin/p/user"
LIST_VIEW_SLUG = "app_users_admin_useradmin_listview"

PINNED_TABLE = "plainadmin_pinnednavitem"
USER_TABLE = "users_user"

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
# `select_objects_by_id()` builds the selection with `is_in()`, which binds
# the ids as one array parameter -- the same statement whether one row or
# fifty were ticked.
USERS_BY_SELECTED_IDS = (
    'UPDATE "users_user" SET "is_admin" = %s '
    'WHERE "users_user"."id" = ANY(%s::bigint[])'
)


def test_a_page_render_reads_only_the_pinned_view_slugs():
    """registry.get_nav_tabs() and AdminView's template context, in that order."""
    admin_client = make_admin_client()

    with capture_spans() as spans:
        assert admin_client.get(LIST_URL).status_code == 200

    assert span_sql_statements(spans, table=PINNED_TABLE) == [
        NAV_TAB_SLUGS,
        PINNED_SLUGS,
    ]


def test_pinning_reads_only_the_order_column():
    admin_client = make_admin_client()

    with capture_spans() as spans:
        response = admin_client.post(
            "/admin/_/pin", form_data={"view_slug": LIST_VIEW_SLUG}
        )
    assert response.status_code == 302

    sql = span_sql_statements(spans, table=PINNED_TABLE)
    assert len(sql) == 4
    assert sql[0].startswith('SELECT COUNT(*) AS "__count"')
    assert sql[1] == MAX_ORDER
    # The row itself is still a get_or_create(): SELECT, then INSERT.
    assert sql[2].startswith('SELECT "plainadmin_pinnednavitem"."id"')
    assert sql[3].startswith('INSERT INTO "plainadmin_pinnednavitem"')


def test_reordering_reads_only_the_pinned_view_slugs():
    admin_client = make_admin_client()
    user = User.query.get(username="admin")
    PinnedNavItem.query.create(user=user, view_slug=LIST_VIEW_SLUG, order=0)

    with capture_spans() as spans:
        response = admin_client.post(
            "/admin/_/reorder", form_data={"slugs": f'["{LIST_VIEW_SLUG}"]'}
        )
    assert response.status_code == 200

    sql = span_sql_statements(spans, table=PINNED_TABLE)
    assert len(sql) == 2
    assert sql[0] == PINNED_SLUGS
    assert sql[1].startswith('UPDATE "plainadmin_pinnednavitem" SET "order" = %s')


def test_the_detail_view_looks_its_object_up_by_id():
    admin_client = make_admin_client()
    user = User.query.create(username="subject")

    with capture_spans() as spans:
        assert admin_client.get(f"{LIST_URL}/{user.id}").status_code == 200

    # Two lookups with the same shape: the session resolving the logged-in
    # user, then AdminModelDetailView.get_object().
    assert span_sql_statements(spans, table=USER_TABLE) == [USER_BY_ID, USER_BY_ID]


def test_an_action_matches_the_selected_ids_with_any_of():
    admin_client = make_admin_client()
    a = User.query.create(username="a")
    b = User.query.create(username="b")

    with capture_spans() as spans:
        response = admin_client.post(
            LIST_URL,
            form_data={"action_name": "Make admin", "action_ids": f"{a.id},{b.id}"},
        )
    assert response.status_code == 302

    # select_objects_by_id() keeps the queryset lazy, so the membership test
    # lands on the UPDATE the action performs.
    assert span_sql_statements(spans, table=USER_TABLE) == [
        USER_BY_ID,
        USERS_BY_SELECTED_IDS,
    ]
