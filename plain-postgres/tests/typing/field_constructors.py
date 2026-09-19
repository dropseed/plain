"""What `types.pyi` promises about each field constructor.

The stub is what gives a field its value type and its nullability, and its
overloads are what refuse argument combinations the runtime would refuse.
Everything here is the stub's side of the contract only -- that the stub
matches the runtime constructors is `tests/internal/test_stub_runtime_
conformance.py`, because no type checker can see that far.
"""

from __future__ import annotations

from datetime import datetime
from typing import assert_type

from plain.postgres import Field, types
from plain.postgres.base import Model
from plain.postgres.fields.binary import BinaryField
from plain.postgres.fields.encrypted import EncryptedTextField
from plain.postgres.fields.temporal import DateTimeField
from plain.postgres.fields.text import TextField


def must_accept_allow_null_widening_the_value_type() -> None:
    assert_type(types.TextField(max_length=10), TextField[str])
    assert_type(
        types.TextField(max_length=10, allow_null=True, default=None),
        TextField[str | None],
    )


def must_accept_the_db_owned_overloads() -> None:
    # `create_now=True` picks the init=False overload and stays non-nullable.
    assert_type(types.DateTimeField(create_now=True), DateTimeField[datetime])


def must_reject_a_non_empty_encrypted_default() -> None:
    # EncryptedTextField takes `default=""` and nothing else -- the empty
    # default exists so the column can be added to a populated table.
    # Runtime half: tests/public/test_only_empty_defaults.py.
    types.EncryptedTextField(default="hunter2")  # ty: ignore[no-matching-overload]


def must_reject_a_non_empty_binary_default() -> None:
    types.BinaryField(default=b"data")  # ty: ignore[no-matching-overload]


def must_reject_a_none_default_without_allow_null() -> None:
    # `default=None` on a NOT NULL column would fail on insert, so the stub
    # pairs the two. Runtime half: tests/public/test_encrypted_fields.py.
    types.EncryptedJSONField(required=False, default=None)  # ty: ignore[no-matching-overload]


def must_reject_choices_on_an_encrypted_field() -> None:
    # Choice filtering on ciphertext silently matches nothing, so the stub
    # never inherited TextField's `choices=`.
    types.EncryptedTextField(choices=[("a", "A")])  # ty: ignore[no-matching-overload]


def must_accept_the_empty_defaults() -> None:
    assert_type(
        types.EncryptedTextField(required=False, default=""), EncryptedTextField[str]
    )
    assert_type(
        types.BinaryField(required=False, default=b""), BinaryField[bytes | memoryview]
    )


class OptionalByDefault(Model):
    """`default=` -- not nullability -- is what makes a field omittable."""

    required_note: Field[str | None] = types.TextField(
        max_length=10, allow_null=True, required=False
    )
    optional_note: Field[str | None] = types.TextField(
        max_length=10, allow_null=True, required=False, default=None
    )


def must_accept_omitting_a_field_with_a_default() -> None:
    OptionalByDefault(required_note="x")


def must_reject_omitting_a_nullable_field_without_a_default() -> None:
    # `required_note` is nullable but passed no `default=`, so it is still a
    # required constructor argument. This is the rule people trip over.
    OptionalByDefault()  # ty: ignore[missing-argument]
