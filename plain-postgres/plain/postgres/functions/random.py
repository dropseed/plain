from __future__ import annotations

from typing import TYPE_CHECKING, Any

from plain.postgres.expressions import Func
from plain.postgres.fields import TextField

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection
    from plain.postgres.sql.compiler import SQLCompiler


DEFAULT_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"


class RandomString(Func):
    """Parameter-free SQL expression that produces an N-char random string.

    Randomness comes from ``gen_random_uuid()`` (OS CSPRNG-backed). Each
    character draws one byte (0-255) and reduces it via ``mod(byte, len)``,
    so any ``len(alphabet)`` that isn't a power of two (16, 32, 64, 128)
    produces a non-uniform distribution. The default 36-char alphabet has
    ~12% over-representation on the first 4 characters (``256 mod 36 == 4``).

    Intended for short identifiers, slugs, and tokens. Pass a power-of-two
    ``alphabet=`` when uniformity matters; use a different mechanism entirely
    for anything security-sensitive.
    """

    output_field = TextField()

    def __init__(
        self,
        length: int,
        alphabet: str = DEFAULT_ALPHABET,
    ) -> None:
        if length < 1:
            raise ValueError("RandomString length must be >= 1")
        if not alphabet:
            raise ValueError("RandomString alphabet must be non-empty")
        if len(alphabet) > 256:
            raise ValueError(
                "RandomString alphabet must be at most 256 characters "
                f"(got {len(alphabet)})."
            )
        # `%` collides with psycopg's placeholder syntax and `'` would need
        # escaping inside the DDL string literal. Neither is a reasonable
        # character for a token/slug alphabet; reject both so the SQL stays
        # simple and the generated DEFAULT compares cleanly byte-for-byte
        # against pg_get_expr output.
        if "%" in alphabet or "'" in alphabet:
            raise ValueError("RandomString alphabet must not contain '%' or \"'\".")
        self.length = length
        self.alphabet = alphabet
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
        # `mod(a, b)` rather than `a % b` — psycopg would mistake `%` for a
        # placeholder. Alphabet is guaranteed by __init__ to contain neither
        # `%` nor `'`, so no escaping is needed here.
        alpha_len = len(self.alphabet)
        char_sql = (
            f"substr('{self.alphabet}', "
            f"1 + mod(get_byte("
            f"decode(replace(gen_random_uuid()::text, '-', ''), 'hex'), 0"
            f"), {alpha_len}), 1)"
        )
        return "(" + " || ".join([char_sql] * self.length) + ")", []
