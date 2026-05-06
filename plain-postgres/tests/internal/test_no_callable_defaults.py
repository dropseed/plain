"""Callable values are rejected as `default=` at model-definition time."""

from __future__ import annotations

import uuid

import pytest

from plain.postgres import fields as plain_fields
from plain.postgres.fields.json import JSONField


def _make_token() -> str:
    return uuid.uuid4().hex


@pytest.mark.parametrize(
    "field_factory",
    [
        lambda: plain_fields.TextField(default=lambda: "x"),
        lambda: plain_fields.TextField(default=_make_token),
        lambda: plain_fields.TextField(default=uuid.uuid4),
        lambda: JSONField(default=dict),
        lambda: JSONField(default=list),
    ],
    ids=["lambda", "function", "uuid.uuid4", "dict-class", "list-class"],
)
def test_callable_default_rejected(field_factory):
    with pytest.raises(TypeError, match="static literal"):
        field_factory()


@pytest.mark.parametrize(
    "field_factory",
    [
        lambda: JSONField(default={}),
        lambda: JSONField(default=[]),
        lambda: plain_fields.TextField(default="x"),
        lambda: plain_fields.IntegerField(default=0),
        lambda: plain_fields.TextField(),
    ],
    ids=["empty-dict", "empty-list", "string", "int", "no-default"],
)
def test_literal_default_accepted(field_factory):
    field_factory()


def test_mutable_default_deep_copied_across_instances():
    """A literal mutable default must produce a fresh object each call, so
    mutations from one instance don't leak into another."""
    field = JSONField(default={})
    a = field.get_default()
    a["leaked"] = True
    b = field.get_default()
    assert b == {}
