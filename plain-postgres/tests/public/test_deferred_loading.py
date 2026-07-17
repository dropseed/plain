"""Characterization of deferred field loading via .only() / .defer().

This file pins how deferred fields currently behave -- which fields are
deferred, that they load the correct value on access, and how many queries
that access costs -- so a future change shows up as a diff to these tests.
"""

from __future__ import annotations

from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.postgres.test import capture_queries


def test_only_defers_unlisted_fields():
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id", "name").get()
    assert widget.get_deferred_fields() == {"size"}


def test_defer_marks_named_field_deferred():
    Widget.query.create(name="W", size="L")
    widget = Widget.query.defer("size").get()
    assert widget.get_deferred_fields() == {"size"}


def test_deferred_field_loads_correct_value():
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id").get()
    assert widget.name == "W"
    assert widget.size == "L"


def test_listed_field_is_available_without_a_query():
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id", "name").get()
    with capture_queries() as queries:
        _ = widget.name
    assert len(queries) == 0


def test_refresh_from_db_reloads_values():
    widget = Widget.query.create(name="W", size="L")
    Widget.query.filter(id=widget.id).update(name="changed")
    widget.refresh_from_db()
    assert widget.name == "changed"


def test_deferred_field_access_query_count():
    # WAS: each deferred field loaded in its own query (two fields = two
    # queries). NOW: the first deferred access hydrates every still-missing
    # field, so the second field needs no further query.
    Widget.query.create(name="W", size="L")
    widget = Widget.query.only("id").get()

    with capture_queries() as first:
        _ = widget.name
    assert len(first) == 1
    with capture_queries() as second:
        _ = widget.size
    assert len(second) == 0


def test_deferred_fk_column_loads_only_the_fk():
    # The foreign key descriptor is the partial-related-instance fast path:
    # hydrating other deferred columns just to materialize a related-object
    # handle would defeat the optimization. So accessing a deferred FK loads
    # only the FK column, not the whole source row -- the contrast to the
    # scalar-field rule pinned by test_deferred_field_access_query_count.
    tag = Tag.query.create(name="t")
    widget = Widget.query.create(name="W", size="L")
    WidgetTag.query.create(widget=widget, tag=tag)

    widget_tag = WidgetTag.query.only("id").get()
    assert widget_tag.get_deferred_fields() == {"widget", "tag"}

    # Accessing the deferred FK loads exactly one column (the FK column).
    with capture_queries() as queries:
        _ = widget_tag.widget
    assert len(queries) == 1
    # The other deferred FK column is still deferred -- not hydrated as a
    # side effect of the first FK access.
    assert "tag" in widget_tag.get_deferred_fields()
