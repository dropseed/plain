"""M2M + unique-constraint coverage using the Widget/Tag/WidgetTag fixture.

The relationships fixture is the designated M2M test model — these tests
exercise ManyToManyField accessors, the through model, and the Widget-specific
unique constraint that produces a realistic ValidationError on duplicate create.
"""

from typing import cast

import pytest
from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.postgres import transaction
from plain.postgres.fields.related import ManyToManyField


def test_create_unique_constraint(db):
    Widget.query.create(name="Toyota", size="Tundra")

    # No pre-check: the duplicate is rejected by the database and mapped to a
    # ValidationError. Wrap in atomic() so the savepoint rolls back and the
    # transaction stays usable for the count() below.
    with pytest.raises(ValidationError) as e:
        with transaction.atomic():
            Widget.query.create(name="Toyota", size="Tundra")

    assert e.value.messages == ["A widget with this name and size already exists."]
    assert NON_FIELD_ERRORS in e.value.error_dict

    assert Widget.query.count() == 1


def test_update_or_create_unique_constraint(db):
    Widget.query.update_or_create(name="Toyota", size="Tundra")
    Widget.query.update_or_create(name="Toyota", size="Tundra")

    assert Widget.query.count() == 1


def test_many_to_many_forward_accessor(db):
    """Test that the forward ManyToManyField accessor works."""
    widget = Widget.query.create(name="Tesla", size="Model 3")
    gps = Tag.query.create(name="GPS")
    sunroof = Tag.query.create(name="Sunroof")

    # Add tags to the widget
    widget.tags.add(gps, sunroof)

    # Verify tags are accessible through forward accessor
    assert widget.tags.query.count() == 2
    tag_names = {f.name for f in widget.tags.query.all()}
    assert tag_names == {"GPS", "Sunroof"}


def test_many_to_many_reverse_accessor(db):
    """Test that the reverse ManyToManyField accessor works."""
    widget1 = Widget.query.create(name="Tesla", size="Model 3")
    widget2 = Widget.query.create(name="Toyota", size="Camry")
    gps = Tag.query.create(name="GPS")

    # Add the same tag to multiple widgets
    widget1.tags.add(gps)
    widget2.tags.add(gps)

    # Verify widgets are accessible through reverse accessor
    assert gps.widgets.query.count() == 2
    widget_sizes = {c.size for c in gps.widgets.query.all()}
    assert widget_sizes == {"Model 3", "Camry"}


def test_many_to_many_remove(db):
    """Test removing items from a ManyToManyField."""
    widget = Widget.query.create(name="Honda", size="Accord")
    gps = Tag.query.create(name="GPS")
    sunroof = Tag.query.create(name="Sunroof")
    leather = Tag.query.create(name="Leather Seats")

    widget.tags.add(gps, sunroof, leather)
    assert widget.tags.query.count() == 3

    # Remove one tag
    widget.tags.remove(sunroof)
    assert widget.tags.query.count() == 2
    tag_names = {f.name for f in widget.tags.query.all()}
    assert tag_names == {"GPS", "Leather Seats"}


def test_many_to_many_clear(db):
    """Test clearing all items from a ManyToManyField."""
    widget = Widget.query.create(name="BMW", size="X5")
    gps = Tag.query.create(name="GPS")
    sunroof = Tag.query.create(name="Sunroof")

    widget.tags.add(gps, sunroof)
    assert widget.tags.query.count() == 2

    # Clear all tags
    widget.tags.clear()
    assert widget.tags.query.count() == 0


def test_value_from_object_returns_related_objects(db):
    """ManyToManyField.value_from_object must return the currently-related
    objects. ModelForm's `model_to_dict` calls this when given an instance
    so the form can populate `initial` for the M2M field — a regression
    here breaks UpdateView for any model with an M2M.
    """
    widget = Widget.query.create(name="Subaru", size="Outback")
    gps = Tag.query.create(name="GPS")
    sunroof = Tag.query.create(name="Sunroof")
    widget.tags.add(gps, sunroof)

    field = cast(ManyToManyField, Widget._model_meta.get_forward_field("tags"))
    result = field.value_from_object(widget)

    assert {t.name for t in result} == {"GPS", "Sunroof"}


def test_value_from_object_unsaved_instance_returns_empty(db):
    """An unsaved instance has no related rows; value_from_object should
    return an empty list rather than crash.
    """
    widget = Widget(name="Mazda", size="3")
    field = cast(ManyToManyField, Widget._model_meta.get_forward_field("tags"))
    assert list(field.value_from_object(widget)) == []


def test_many_to_many_through_model(db):
    """Test accessing the through model directly."""
    widget = Widget.query.create(name="Ford", size="Mustang")
    gps = Tag.query.create(name="GPS")

    # Create relationship through the through model
    WidgetTag.query.create(widget=widget, tag=gps)

    # Verify the relationship exists
    assert widget.tags.query.count() == 1
    assert widget.tags.query.first() == gps

    # Verify we can query the through model
    through_instances = WidgetTag.query.filter(widget=widget)
    assert through_instances.count() == 1
    through_instance = through_instances.first()
    assert through_instance is not None
    assert through_instance.tag == gps
