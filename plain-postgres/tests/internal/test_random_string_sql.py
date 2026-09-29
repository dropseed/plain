"""The exact SQL `RandomStringField` persists as its column DEFAULT.

Below the contract: users see a random token of the right length and alphabet
(`tests/public/test_random_string_field.py`). This pins the generated SQL so a
refactor of the slicing math fails here rather than by silently changing an
already-persisted DEFAULT and making convergence see drift forever.
"""

from plain.postgres.ddl import compile_database_default_sql
from plain.postgres.functions.random import RandomString


# Random string SQL
#
# Pin the exact SQL shape so a refactor that breaks the slicing math
# fails loudly instead of silently changing the persisted DEFAULT.
def random_string_default_sql(length: int) -> str:
    return compile_database_default_sql(RandomString(length=length))


def test_short_length_uses_single_uuid_slice():
    assert (
        random_string_default_sql(16)
        == "substr(replace(gen_random_uuid()::text, '-', ''), 1, 16)"
    )


def test_exact_uuid_length_uses_single_uuid_slice():
    assert (
        random_string_default_sql(32)
        == "substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
    )


def test_over_uuid_length_concats_uuid_slices():
    assert random_string_default_sql(40) == (
        "(substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
        " || substr(replace(gen_random_uuid()::text, '-', ''), 1, 8))"
    )


def test_multiple_full_uuids():
    assert random_string_default_sql(64) == (
        "(substr(replace(gen_random_uuid()::text, '-', ''), 1, 32)"
        " || substr(replace(gen_random_uuid()::text, '-', ''), 1, 32))"
    )
