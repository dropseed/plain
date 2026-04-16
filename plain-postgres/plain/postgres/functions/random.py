from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.expressions import Func
from plain.postgres.fields import TextField

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.sql.compiler import SQLCompiler


_UUID_HEX_CHARS = 32


class RandomString(Func):
    """Parameter-free SQL expression that produces an N-char random hex string.

    Slices ``gen_random_uuid()`` (OS CSPRNG-backed) directly: each call
    contributes 32 hex characters; longer values concatenate additional UUID
    slices. Suitable for tokens, slugs, and short identifiers.
    """

    output_field = TextField()

    def __init__(self, length: int) -> None:
        if length < 1:
            raise ValueError("RandomString length must be >= 1")
        self.length = length
        super().__init__()

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: DatabaseConnection,
        function: str | None = None,
        template: str | None = None,
        arg_joiner: str | None = None,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        full, leftover = divmod(self.length, _UUID_HEX_CHARS)
        parts = [
            f"substr(replace(gen_random_uuid()::text, '-', ''), 1, {_UUID_HEX_CHARS})"
        ] * full
        if leftover:
            parts.append(
                f"substr(replace(gen_random_uuid()::text, '-', ''), 1, {leftover})"
            )
        if len(parts) == 1:
            return parts[0], []
        return "(" + " || ".join(parts) + ")", []
