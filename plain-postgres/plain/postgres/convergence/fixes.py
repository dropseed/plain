from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constraints import BaseConstraint, CheckConstraint
from ..db import get_connection
from ..dialect import quote_name


@dataclass
class AddConstraintFix:
    """Add a missing constraint using NOT VALID for check constraints."""

    table: str
    constraint: BaseConstraint
    model: Any

    def describe(self) -> str:
        suffix = " (NOT VALID)" if isinstance(self.constraint, CheckConstraint) else ""
        return f"{self.table}: add {self.constraint.name}{suffix}"

    def apply(self, cursor: Any) -> str:
        conn = get_connection()
        with conn.schema_editor(collect_sql=True) as editor:
            sql = self.constraint.create_sql(self.model, editor)
        sql_str = str(sql)

        # Check constraints use NOT VALID to avoid a full table scan under
        # ACCESS EXCLUSIVE. Validation happens in a separate pass.
        if isinstance(self.constraint, CheckConstraint):
            sql_str += " NOT VALID"

        cursor.execute(sql_str)
        return sql_str


@dataclass
class ValidateConstraintFix:
    """Validate a NOT VALID constraint (SHARE UPDATE EXCLUSIVE — doesn't block writes)."""

    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: validate {self.name}"

    def apply(self, cursor: Any) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} VALIDATE CONSTRAINT {quote_name(self.name)}"
        cursor.execute(sql)
        return sql


@dataclass
class DropConstraintFix:
    table: str
    name: str

    def describe(self) -> str:
        return f"{self.table}: drop {self.name}"

    def apply(self, cursor: Any) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} DROP CONSTRAINT {quote_name(self.name)}"
        cursor.execute(sql)
        return sql


Fix = AddConstraintFix | ValidateConstraintFix | DropConstraintFix
