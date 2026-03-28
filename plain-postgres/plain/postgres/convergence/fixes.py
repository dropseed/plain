from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..constraints import BaseConstraint
from ..db import get_connection
from ..dialect import quote_name


@dataclass
class ColumnTypeFix:
    table: str
    column: str
    actual: str
    expected: str

    def describe(self) -> str:
        return f"{self.table}.{self.column}: {self.actual} → {self.expected}"

    def apply(self, cursor: Any) -> str:
        sql = f"ALTER TABLE {quote_name(self.table)} ALTER COLUMN {quote_name(self.column)} TYPE {self.expected}"
        cursor.execute(sql)
        return sql


@dataclass
class AddConstraintFix:
    table: str
    constraint: BaseConstraint
    model: Any

    def describe(self) -> str:
        return f"{self.table}: add {self.constraint.name}"

    def apply(self, cursor: Any) -> str:
        conn = get_connection()
        with conn.schema_editor(collect_sql=True) as editor:
            sql = self.constraint.create_sql(self.model, editor)
        sql_str = str(sql)
        cursor.execute(sql_str)
        return sql_str


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


Fix = ColumnTypeFix | AddConstraintFix | DropConstraintFix
