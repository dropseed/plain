"""Float-annotated settings accept int values (PEP 484 numeric tower).

`PLAIN_X=30` parses to an int via JSON, and `X = 30` in settings.py is the
natural spelling — both must satisfy a `float` annotation, stored as float.
bool stays rejected (an int subclass, but never a number here).
"""

from __future__ import annotations

import pytest

from plain.exceptions import ImproperlyConfigured
from plain.runtime.user_settings import SettingDefinition


def _float_setting() -> SettingDefinition:
    return SettingDefinition(
        name="EXAMPLE_TIMEOUT", default_value=60.0, annotation=float
    )


def test_int_value_coerced_to_float():
    definition = _float_setting()
    definition.set_value(30, source="env")
    assert definition.value == 30.0
    assert isinstance(definition.value, float)


def test_float_value_unchanged():
    definition = _float_setting()
    definition.set_value(2.5, source="explicit")
    assert definition.value == 2.5


def test_bool_value_still_rejected():
    definition = _float_setting()
    with pytest.raises(ImproperlyConfigured):
        definition.set_value(True, source="explicit")


def test_int_annotation_still_rejects_float():
    definition = SettingDefinition(
        name="EXAMPLE_COUNT", default_value=4, annotation=int
    )
    with pytest.raises(ImproperlyConfigured):
        definition.set_value(4.5, source="explicit")
