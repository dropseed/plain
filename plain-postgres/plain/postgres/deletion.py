from __future__ import annotations


class OnDelete:
    """Sentinel marking an on_delete action.

    Each valid action is a single `OnDelete` instance exported from
    ``plain.postgres`` (CASCADE, SET_NULL, RESTRICT, NO_ACTION). Cascading
    is enforced entirely by Postgres via the corresponding ``ON DELETE``
    clause — there is no application-level traversal.
    """

    __slots__ = ("name", "sql_clause", "confdeltype")

    def __init__(self, name: str, sql_clause: str, confdeltype: str) -> None:
        self.name = name
        self.sql_clause = sql_clause
        self.confdeltype = confdeltype

    def __repr__(self) -> str:
        return f"<plain.postgres.{self.name}>"


#: Child rows are deleted by Postgres when the parent is deleted.
CASCADE = OnDelete("CASCADE", " ON DELETE CASCADE", "c")

#: Child FK columns are set to NULL when the parent is deleted.
#: Requires ``allow_null=True`` on the field.
SET_NULL = OnDelete("SET_NULL", " ON DELETE SET NULL", "n")

#: Deleting the parent fails immediately with IntegrityError if children exist.
#: The check is always immediate — it is not affected by DEFERRABLE.
RESTRICT = OnDelete("RESTRICT", " ON DELETE RESTRICT", "r")

#: Deleting the parent fails at transaction commit if children exist.
#: Respects DEFERRABLE INITIALLY DEFERRED, so constraint violations inside a
#: transaction can be resolved before commit.
NO_ACTION = OnDelete("NO_ACTION", "", "a")


def sql_on_delete(on_delete: OnDelete) -> tuple[str, str]:
    """Return ``(sql_clause, pg_confdeltype_code)`` for an on_delete value."""
    if not isinstance(on_delete, OnDelete):
        raise TypeError(
            "on_delete must be one of plain.postgres.CASCADE, SET_NULL, "
            f"RESTRICT, or NO_ACTION; got {on_delete!r}"
        )
    return (on_delete.sql_clause, on_delete.confdeltype)
