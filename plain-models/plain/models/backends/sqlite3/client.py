from __future__ import annotations

from typing import TYPE_CHECKING

from plain.models.backends.base.client import BaseDatabaseClient

if TYPE_CHECKING:
    from plain.models.connections import DatabaseConfig


class DatabaseClient(BaseDatabaseClient):
    executable_name = "sqlite3"

    @classmethod
    def settings_to_cmd_args_env(
        cls, settings_dict: DatabaseConfig, parameters: list[str]
    ) -> tuple[list[str], None]:
        name = settings_dict.get("NAME") or ""
        args = [cls.executable_name, name, *parameters]
        return args, None
