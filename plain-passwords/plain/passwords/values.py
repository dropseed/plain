from __future__ import annotations

import hmac
from typing import Any, Self

from .hashers import check_password, get_hasher, hash_password, identify_hasher

__all__ = ["HashedPassword"]


class HashedPassword:
    """A stored password — the encoded hash, never the raw input.

    This is the only form a password takes outside the form layer. A column
    declared ``types.TextField(value_type=HashedPassword)`` gets and sets a
    ``HashedPassword``; assigning a raw string is a type error at the call
    site and a ``TypeError`` at write time, so a password can't reach the
    database unhashed.

    A raw password enters through ``from_raw()``, which hashes it
    immediately, and is tested with ``check()``. Nothing hands one back.
    ``HashedPassword`` does not validate raw passwords — that belongs at the
    boundary that receives them (``validate_raw_password``, which the
    password form field runs).
    """

    __slots__ = ("encoded",)

    def __init__(self, encoded: str) -> None:
        self.encoded = encoded

    @classmethod
    def from_raw(cls, raw: str) -> Self:
        """Hash a raw password with the configured hasher."""
        return cls(hash_password(raw))

    @classmethod
    def from_db(cls, raw: Any, /) -> Self:
        """Rebuild from the stored column value (the `ValueType` protocol)."""
        return cls(raw)

    def to_db(self) -> str:
        """The encoded hash, as stored (the `ValueType` protocol)."""
        return self.encoded

    def check(self, raw: str) -> bool:
        """Whether this raw password is the one behind this hash."""
        return check_password(raw, self.encoded)

    def needs_rehash(self) -> bool:
        """Whether the hash should be regenerated with the preferred hasher.

        True when the encoded hash uses a different algorithm than the first
        entry in ``PASSWORD_HASHERS``, when that hasher wants different
        parameters (work factor, salt entropy), or when the hash can't be
        identified at all. Rehashing needs the raw password, so the caller
        does it right after a successful ``check()``.
        """
        preferred = get_hasher("default")
        try:
            hasher = identify_hasher(self.encoded)
        except ValueError:
            # Gibberish, or a hasher that's no longer installed.
            return True
        if hasher.algorithm != preferred.algorithm:
            return True
        return preferred.must_update(self.encoded)

    def __str__(self) -> str:
        return self.encoded

    def __repr__(self) -> str:
        # Deliberately opaque: a hash shouldn't land in a log line or a
        # traceback just because something repr'd the object holding it.
        return "<HashedPassword>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HashedPassword):
            return NotImplemented
        return hmac.compare_digest(self.encoded, other.encoded)

    def __hash__(self) -> int:
        return hash(self.encoded)
