"""`ManyToManyField.value_from_object` -- the hook ModelForm loads initial from.

Below the contract: it is reached through `_model_meta.get_forward_field`, and
the user-visible behavior it supports (an UpdateView pre-selecting the related
rows) is asserted in `tests/public/test_modelform_roundtrip.py`.
"""

from typing import cast

from app.examples.models.relationships import Tag, Widget
from plain.postgres.fields.related import ManyToManyField


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
