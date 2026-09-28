"""Python 3.14 deferred annotations (PEP 649) meet the documented
TYPE_CHECKING-only foreign key pattern.

``plain-postgres.md`` tells users to write a string-referenced foreign key
like this::

    if TYPE_CHECKING:
        from app.users.models import User

    user: Field[User] = types.ForeignKeyField("users.User", on_delete=postgres.CASCADE)

Before Python 3.14, ``inspect.get_annotations()``'s default (VALUE) format
only ever evaluated a *string* annotation (under ``from __future__ import
annotations``) or left an already-evaluated one alone -- either way, a name
that exists only under ``TYPE_CHECKING`` was never a problem for
``plain preflight``. Python 3.14 defers annotation evaluation instead (PEP
649): a module with no postponed-annotations import now evaluates
``Field[User]`` lazily, and VALUE format forces that evaluation, raising
``NameError`` for ``User``.

This module is deliberately **not** ``from __future__ import annotations`` --
that's the whole point, since a postponed-annotations module was never
affected by this bug (its annotations were already strings).
``test_this_module_does_not_postpone_annotations`` proves it, so every other
test here means what it says.

The fixture models are built with `_class_in_module`, each in a module of its
own, rather than defined directly at this file's top level. That's not about
postponing (none of them are) -- it's so the `TYPE_CHECKING`-only name lives
only in the annotation text passed to `exec`, invisible to `ty` and `ruff`.
Written directly in this file, `Field[Project]` would be an undefined name to
both of them; here it's undefined only to the *runtime*, under deferred
evaluation, which is exactly the bug.
"""

import inspect
import sys
from types import ModuleType
from typing import Any, ClassVar

import pytest
from plain.postgres import Field, types
from plain.postgres.base import Model
from plain.postgres.preflight.models import (
    CheckForeignKeyAnnotatedAsValue,
    CheckTypedConstruction,
    foreign_keys_annotated_as_values,
)
from plain.postgres.registry import models_registry

from plain import postgres


def _class_in_module(
    module_name: str, class_name: str, source: str, **names: Any
) -> type:
    """Build a class in a module of its own, so its `TYPE_CHECKING`-only
    annotation name lives only in `source` -- never written where `ty` or
    `ruff` would see it. `dont_inherit` keeps it from picking up this file's
    own compiler flags, though this file has none to pass down.
    """
    module = ModuleType(module_name)
    module.__dict__.update(names)
    sys.modules[module_name] = module
    exec(  # noqa: S102
        compile(source, f"<{module_name}>", "exec", dont_inherit=True),
        module.__dict__,
    )
    return module.__dict__[class_name]


def test_this_module_does_not_postpone_annotations():
    """Proof the module docstring's claim is true: a class defined here with
    an unresolvable annotation raises NameError under VALUE format, which
    only happens without `from __future__ import annotations`. If this ever
    starts passing, every other test in this file would be proving nothing.
    """

    class _Probe:
        marker: _NeverDefined  # noqa: F821  # ty: ignore[unresolved-reference]

    with pytest.raises(NameError):
        inspect.get_annotations(_Probe)


# A never-registered target: `_related_model()` can never resolve it, no
# matter how the FK's own annotation reads. Every fixture below points at it.
_UNRESOLVABLE_TARGET = "examples.NeverRegisteredPy314Project"


# ---------------------------------------------------------------------------
# (1) `Field[Project]`, `Project` importable only under TYPE_CHECKING
# ---------------------------------------------------------------------------

FieldWrapped = _class_in_module(
    "tests.py314_field_wrapped",
    "FieldWrapped",
    "class FieldWrapped(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    project: Field[Project] = types.ForeignKeyField(\n"
    f"        {_UNRESOLVABLE_TARGET!r}, on_delete=postgres.CASCADE\n"
    "    )\n",
    Model=Model,
    types=types,
    postgres=postgres,
    Field=Field,
)


def test_field_wrapped_type_checking_only_reference_does_not_raise():
    """The documented spelling. Evaluating `Field[Project]` under deferred
    annotations can't resolve `Project`, but FORWARDREF format resolves
    `Field` (always a real runtime import) and leaves `Project` as a
    `ForwardRef` -- `_classify` never needs to look at it to know this is a
    field, not a leaked value."""
    assert foreign_keys_annotated_as_values(FieldWrapped) == []


# ---------------------------------------------------------------------------
# (2) The same field, annotated bare `Project` instead of `Field[Project]`
# ---------------------------------------------------------------------------

BareName = _class_in_module(
    "tests.py314_bare_name",
    "BareName",
    "class BareName(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    project: Project = types.ForeignKeyField(\n"
    f"        {_UNRESOLVABLE_TARGET!r}, on_delete=postgres.CASCADE\n"
    "    )\n",
    Model=Model,
    types=types,
    postgres=postgres,
)


def test_bare_type_checking_only_reference_does_not_raise_and_is_unknown():
    """The wrong spelling `postgres.foreign_key_annotated_as_value` exists to
    catch -- and under a *postponed*-annotations module it's caught, because
    the annotation is a string and its whole text (`"Project"`) is evidence
    `_classify` can match against the field's own related model. Here the
    whole annotation collapses to a single unresolvable `ForwardRef`
    instead, and the FK's target is never registered, so `_related_model()`
    can't resolve it either -- no evidence either way. That's a known,
    documented gap for deferred annotations: conservatively silent
    (`_UNKNOWN`) rather than a guess, same as every other shape this check
    can't read with confidence.
    """
    assert foreign_keys_annotated_as_values(BareName) == []


# ---------------------------------------------------------------------------
# (3) A non-field attribute annotated `ClassVar[Project]`
# ---------------------------------------------------------------------------

ClassVarAttribute = _class_in_module(
    "tests.py314_classvar_attribute",
    "ClassVarAttribute",
    "class ClassVarAttribute(Model):\n"
    "    model_options = postgres.Options(package_label='examples')\n"
    "    name: Field[str] = types.TextField(max_length=10)\n"
    "    # Class-level metadata, not a field -- ClassVar keeps it out of the\n"
    "    # synthesized constructor.\n"
    "    default_related: ClassVar[Project] = None\n",
    Model=Model,
    types=types,
    postgres=postgres,
    ClassVar=ClassVar,
)


def test_classvar_type_checking_only_reference_is_not_a_leak(monkeypatch):
    """Scoped to just this fixture -- `CheckTypedConstruction` otherwise only
    inspects `models_registry.get_models()`, which none of these unregistered
    fixtures are in."""
    monkeypatch.setattr(models_registry, "get_models", lambda **_: [ClassVarAttribute])
    results = CheckTypedConstruction().run()
    leaks = [r.fix for r in results if r.id == "postgres.field_leaks_into_constructor"]
    assert leaks == []


# ---------------------------------------------------------------------------
# (4) Both registered checks, run over every fixture above, must not raise
# ---------------------------------------------------------------------------


def test_registered_checks_survive_every_fixture(monkeypatch):
    """Not a claim about what either check reports -- only that FORWARDREF
    keeps `inspect.get_annotations()` from raising NameError, for every shape
    above, the way `plain preflight` would actually encounter them."""
    fixtures = [FieldWrapped, BareName, ClassVarAttribute]
    monkeypatch.setattr(models_registry, "get_models", lambda **_: fixtures)

    CheckTypedConstruction().run()
    CheckForeignKeyAnnotatedAsValue().run()
