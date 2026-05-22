"""Characterization of deferred field loading via .only() / .defer().

This file pins how deferred fields currently behave -- which fields are
deferred, that they load the correct value on access, and how many queries
that access costs -- so a future change shows up as a diff to these tests.
"""

from __future__ import annotations

from app.examples.models.relationships import Widget

from plain.postgres.db import get_connection


def _count_queries(fn):
    conn = get_connection()
    previous = conn.force_debug_cursor
    conn.force_debug_cursor = True
    conn.queries_log.clear()
    try:
        result = fn()
        return result, len(conn.queries_log)
    finally:
        conn.force_debug_cursor = previous


def test_only_defers_unlisted_fields(db):
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id", "name").get()
    assert widget.get_deferred_fields() == {"size"}


def test_defer_marks_named_field_deferred(db):
    Widget.query.create(name="W", size="L")
    widget = Widget.query.defer("size").get()
    assert widget.get_deferred_fields() == {"size"}


def test_deferred_field_loads_correct_value(db):
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id").get()
    assert widget.name == "W"
    assert widget.size == "L"


def test_listed_field_is_available_without_a_query(db):
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id", "name").get()
    _, queries = _count_queries(lambda: widget.name)
    assert queries == 0


def test_refresh_from_db_reloads_values(db):
    widget = Widget.query.create(name="W", size="L")
    Widget.query.filter(id=widget.id).update(name="changed")
    widget.refresh_from_db()
    assert widget.name == "changed"


def test_deferred_field_access_query_count(db):
    # WAS: each deferred field loaded in its own query (two fields = two
    # queries). NOW: the first deferred access hydrates every still-missing
    # field, so the second field needs no further query.
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id").get()

    _, first = _count_queries(lambda: widget.name)
    assert first == 1
    _, second = _count_queries(lambda: widget.size)
    assert second == 0
