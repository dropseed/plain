"""M2M + unique-constraint coverage using the Widget/Tag/WidgetTag fixture.

The relationships fixture is the designated M2M test model — these tests
exercise ManyToManyField accessors, the through model, and the Widget-specific
unique constraint that produces a realistic ValidationError on duplicate create.
"""

import pytest
from app.examples.models.relationships import Tag, Widget, WidgetTag

from plain.exceptions import ValidationError


def test_create_unique_constraint(db):
    Widget.query.create(name="Toyota", size="Tundra")

    with pytest.raises(ValidationError) as e:
        Widget.query.create(name="Toyota", size="Tundra")

    assert (
        str(e)
        == "<ExceptionInfo ValidationError({'__all__': ['A widget with this name and size already exists.']}) tblen=4>"
    )

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
