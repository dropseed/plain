"""The writer writes what `deconstruct()` returns, options included.

`RunSQL` and `RunPython` take their options keyword-only; nothing about the
constructor's signature decides what reaches the file.
"""

from __future__ import annotations

from plain.postgres.migrations import operations
from plain.postgres.migrations.writer import OperationWriter


def touch(models, schema_editor):
    pass


def test_operation_options_are_written() -> None:
    sql, _ = OperationWriter(
        operations.RunSQL("select 1", skip_on_reset=True, no_timeout=True)
    ).serialize()
    python, _ = OperationWriter(
        operations.RunPython(touch, atomic=False, skip_on_reset=True)
    ).serialize()

    assert "skip_on_reset=True" in sql
    assert "no_timeout=True" in sql
    assert "atomic=False" in python
    assert "skip_on_reset=True" in python
