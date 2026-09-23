"""Encrypted fields block every condition that compares ciphertext.

`EncryptedField` declares the blocked methods under `TYPE_CHECKING` with
`Never` parameters, so every call site is rejected; `_build_q` is the runtime
half. The class-wide `ty: ignore[invalid-method-override]` on those
declarations would otherwise hide a block that quietly stopped blocking --
these markers are what notice.

One call per function on purpose: the blocked methods are declared `-> Never`,
so a second call in the same body sits in unreachable code and is never
analyzed -- the marker on it would read as satisfied while proving nothing.

Runtime half: tests/public/test_encrypted_fields.py.
"""

from typing import assert_type

from app.examples.models.encrypted import SecretStore
from plain.postgres.query_utils import Q

# --- text column -----------------------------------------------------------


def must_reject_equals() -> None:
    SecretStore.api_key.equals("x")  # ty: ignore[no-matching-overload]


def must_reject_not_equal() -> None:
    SecretStore.api_key.not_equal("x")  # ty: ignore[no-matching-overload]


def must_reject_gt() -> None:
    SecretStore.api_key.gt("x")  # ty: ignore[invalid-argument-type]


def must_reject_gte() -> None:
    SecretStore.api_key.gte("x")  # ty: ignore[invalid-argument-type]


def must_reject_lt() -> None:
    SecretStore.api_key.lt("x")  # ty: ignore[invalid-argument-type]


def must_reject_lte() -> None:
    SecretStore.api_key.lte("x")  # ty: ignore[invalid-argument-type]


def must_reject_is_in() -> None:
    SecretStore.api_key.is_in(["x"])  # ty: ignore[invalid-argument-type]


def must_reject_contains() -> None:
    SecretStore.api_key.contains("x")  # ty: ignore[invalid-argument-type]


def must_reject_icontains() -> None:
    SecretStore.api_key.icontains("x")  # ty: ignore[invalid-argument-type]


def must_reject_startswith() -> None:
    SecretStore.api_key.startswith("x")  # ty: ignore[invalid-argument-type]


def must_reject_endswith() -> None:
    SecretStore.api_key.endswith("x")  # ty: ignore[invalid-argument-type]


def must_reject_iequals() -> None:
    SecretStore.api_key.iequals("x")  # ty: ignore[invalid-argument-type]


def must_reject_istartswith() -> None:
    SecretStore.api_key.istartswith("x")  # ty: ignore[invalid-argument-type]


def must_reject_iendswith() -> None:
    SecretStore.api_key.iendswith("x")  # ty: ignore[invalid-argument-type]


def must_reject_a_non_empty_string() -> None:
    # "" is stored as plaintext so it stays matchable; anything else is not.
    SecretStore.notes.equals("something")  # ty: ignore[no-matching-overload]


# --- json column -----------------------------------------------------------


def must_reject_json_equals() -> None:
    SecretStore.config.equals({"a": 1})  # ty: ignore[no-matching-overload]


def must_reject_json_not_equal() -> None:
    SecretStore.config.not_equal({"a": 1})  # ty: ignore[no-matching-overload]


def must_reject_json_is_in() -> None:
    SecretStore.config.is_in([{"a": 1}])  # ty: ignore[invalid-argument-type]


def must_reject_an_empty_string_on_a_json_column() -> None:
    # Only text columns store "" as plaintext -- on jsonb it is ciphertext.
    SecretStore.config.equals("")  # ty: ignore[no-matching-overload]


# --- what survives the block -----------------------------------------------


def must_accept_is_null() -> None:
    # The one condition that stays open. No marker here on purpose: a `Never`
    # creeping onto is_null breaks the build.
    assert_type(SecretStore.api_key.is_null(), Q)
    assert_type(SecretStore.api_key.is_null(False), Q)
    assert_type(SecretStore.config.is_null(), Q)


def must_accept_the_deterministically_matchable_values() -> None:
    # `equals(None)` is the ORM's exact-None rewrite, and "" round-trips as
    # plaintext on a text column. The static surface and the runtime guard
    # agree on exactly this set.
    assert_type(SecretStore.api_key.equals(None), Q)
    assert_type(SecretStore.notes.equals(""), Q)
    assert_type(SecretStore.notes.not_equal(""), Q)
    assert_type(SecretStore.config.equals(None), Q)
