"""
`patch` leaves a target holding what it held before the block.
"""

import os
import types

from plain.runtime import settings
from plain.test import patch, raises


class Thing:
    attr = "original"


def test_patch_attribute_restores():
    with patch(Thing, "attr", "changed"):
        assert Thing.attr == "changed"
    assert Thing.attr == "original"


class InheritingThing(Thing):
    pass


def test_patch_inherited_attribute_leaves_nothing_on_the_subclass():
    with patch(InheritingThing, "attr", "changed"):
        assert InheritingThing.attr == "changed"
        assert Thing.attr == "original"
    assert "attr" not in vars(InheritingThing)
    assert InheritingThing.attr == "original"


class ThingWithMethods:
    def describe(self):
        return "a thing with methods"

    @staticmethod
    def double(value):
        return value * 2

    @classmethod
    def name(cls):
        return cls.__name__


def test_patch_staticmethod_restores_a_staticmethod():
    with patch(ThingWithMethods, "double", lambda value: value * 3):
        assert ThingWithMethods.double(2) == 6
    # Called through an instance: a plain function here would receive `self`.
    assert ThingWithMethods().double(2) == 4


def test_patch_classmethod_restores_a_classmethod():
    with patch(ThingWithMethods, "name", lambda: "patched"):
        assert ThingWithMethods.name() == "patched"

    class Child(ThingWithMethods):
        pass

    # A bound method put back in place would still answer for the parent.
    assert Child.name() == "Child"


def test_patch_rejects_a_name_the_target_does_not_have():
    with raises(AttributeError), patch(Thing, "no_such_attribute", "value"):
        pass


def test_patch_mapping_restores_and_removes():
    with patch(os.environ, "PLAIN_TESTING_PATCH_TEST", "on"):
        assert os.environ["PLAIN_TESTING_PATCH_TEST"] == "on"
    assert "PLAIN_TESTING_PATCH_TEST" not in os.environ


def test_patching_a_method_on_an_instance_leaves_nothing_on_the_instance():
    thing = ThingWithMethods()
    assert vars(thing) == {}

    with patch(thing, "describe", lambda: "patched"):
        assert thing.describe() == "patched"

    # A bound method put back in place would sit in the instance's
    # `__dict__`, holding a reference back to the instance.
    assert vars(thing) == {}
    assert thing.describe() == "a thing with methods"


def test_an_instance_attribute_gets_its_own_value_back():
    thing = ThingWithMethods()
    thing.color = "red"  # ty: ignore[unresolved-attribute]

    with patch(thing, "color", "blue"):
        assert thing.color == "blue"  # ty: ignore[unresolved-attribute]

    assert vars(thing) == {"color": "red"}


def test_an_instance_attribute_that_was_the_classes_is_the_classes_again():
    thing = Thing()

    with patch(thing, "attr", "changed"):
        assert thing.attr == "changed"
        assert Thing.attr == "original"

    assert vars(thing) == {}
    assert thing.attr == "original"


def test_a_module_attribute_gets_its_value_back():
    module = types.ModuleType("patched_module")
    module.LIMIT = 10  # ty: ignore[unresolved-attribute]

    with patch(module, "LIMIT", 99):
        assert module.LIMIT == 99

    assert module.LIMIT == 10


class Thermostat:
    def __init__(self) -> None:
        self._degrees = 20
        self.times_set = 0

    @property
    def degrees(self) -> int:
        return self._degrees

    @degrees.setter
    def degrees(self, value: int) -> None:
        self._degrees = value
        self.times_set += 1


def test_a_property_is_set_and_set_back_through_its_setter():
    thermostat = Thermostat()

    with patch(thermostat, "degrees", 30):
        assert thermostat.degrees == 30

    # Deleting it, as for an attribute the instance only inherited, would
    # raise: a property with no deleter can't be deleted.
    assert thermostat.degrees == 20
    assert thermostat.times_set == 2
    assert "degrees" not in vars(thermostat)


class Point:
    __slots__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self.x = x
        self.y = y


def test_a_slot_gets_its_value_back():
    point = Point(1, 2)

    with patch(point, "x", 100):
        assert point.x == 100

    assert point.x == 1
    assert point.y == 2


def test_a_setting_gets_its_value_back_and_stays_a_setting():
    # `override_settings` is the way to change a setting. `patch` reaching
    # one anyway has to leave it as it found it: the settings object keeps
    # its values itself, not in its `__dict__`.
    original = settings.DEBUG

    with patch(settings, "DEBUG", not original):
        assert settings.DEBUG is (not original)

    assert settings.DEBUG is original
    assert "DEBUG" not in vars(settings)
    assert [name for name, _ in settings.get_settings()].count("DEBUG") == 1
