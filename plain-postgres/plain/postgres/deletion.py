from __future__ import annotations


class OnDelete:
    """Sentinel marking an on_delete action.

    Each valid action is a single `OnDelete` instance exported from
    ``plain.postgres`` (CASCADE, SET_NULL, RESTRICT). Cascading is enforced
    entirely by Postgres via the corresponding ``ON DELETE`` clause — there
    is no application-level traversal.
    """

    __slots__ = ("confdeltype", "name", "sql_clause")

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
RESTRICT = OnDelete("RESTRICT", " ON DELETE RESTRICT", "r")
