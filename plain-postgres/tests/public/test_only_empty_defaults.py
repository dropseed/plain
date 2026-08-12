"""EncryptedTextField and BinaryField accept only their empty value as a
default (enforced once in DefaultableField.__init__ via `only_empty_default`).
The empty default exists so the field can be added to a populated table."""

from __future__ import annotations

from typing import Any

import pytest
from plain.postgres import types


@pytest.mark.parametrize(
    ("factory", "bad_default"),
    [
        (types.EncryptedTextField, "hunter2"),
        (types.BinaryField, b"data"),
        # These compare equal to b"" but don't deepcopy or serialize like it —
        # the guard checks the exact type.
        (types.BinaryField, bytearray()),
        (types.BinaryField, memoryview(b"")),
    ],
    ids=["encrypted-non-empty", "binary-non-empty", "bytearray", "memoryview"],
)
def test_non_empty_default_rejected(factory: Any, bad_default: Any) -> None:
    with pytest.raises(ValueError, match="only supports default="):
        factory(required=False, default=bad_default)


@pytest.mark.parametrize(
    ("factory", "empty"),
    [
        (types.EncryptedTextField, ""),
        (types.BinaryField, b""),
    ],
    ids=["encrypted", "binary"],
)
def test_empty_default_requires_not_required(factory: Any, empty: Any) -> None:
    """The default fills the field with an empty value that required=True
    would then reject on every save — the pairing is refused up front."""
    with pytest.raises(ValueError, match="required=False"):
        factory(default=empty)


@pytest.mark.parametrize(
    "factory",
    [types.EncryptedTextField, types.BinaryField],
    ids=["encrypted", "binary"],
)
def test_none_default_allowed_when_nullable(factory: Any) -> None:
    """default=None stays legal on a nullable column, as on every other
    DefaultableField."""
    factory(required=False, allow_null=True, default=None)


def test_encrypted_choices_rejected() -> None:
    """EncryptedTextField deliberately doesn't accept TextField's choices= —
    choice filtering on ciphertext would silently match nothing."""
    with pytest.raises(TypeError, match="choices"):
        types.EncryptedTextField(choices=[("a", "A")])  # ty: ignore[no-matching-overload]


@pytest.mark.parametrize(
    "factory",
    [types.EncryptedTextField, types.BinaryField],
    ids=["encrypted", "binary"],
)
def test_none_default_requires_nullable_and_optional(factory: Any) -> None:
    """default=None needs the full pairing: without allow_null the NOT NULL
    column fails on insert, and without required=False validation rejects the
    defaulted None on every save."""
    with pytest.raises(ValueError, match="allow_null=True and required=False"):
        factory(default=None)
    with pytest.raises(ValueError, match="allow_null=True and required=False"):
        factory(allow_null=True, default=None)
