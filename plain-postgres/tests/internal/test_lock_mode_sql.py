"""LOCK_MODE_SQL has to cover every token in the LockMode Literal.

The `dict[LockMode, str]` annotation only rejects keys that aren't LockMode
tokens — a token added to the Literal with no clause here type-checks fine and
would only fail as a KeyError when someone calls the new lock method.
"""

from typing import get_args

from plain.postgres.dialect import LOCK_MODE_SQL
from plain.postgres.sql import LockMode


def test_every_lock_mode_maps_to_sql():
    assert set(LOCK_MODE_SQL) == set(get_args(LockMode))
