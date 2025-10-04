from __future__ import annotations

from typing import Any

from plain.models.backends.base.client import BaseDatabaseClient


class DatabaseClient(BaseDatabaseClient):
    executable_name = "sqlite3"

    @classmethod
    def settings_to_cmd_args_env(
        cls, settings_dict: dict[str, Any], parameters: list[str]
    ) -> tuple[list[str], None]:
        args = [cls.executable_name, settings_dict["NAME"], *parameters]
        return args, None
