from __future__ import annotations

import os
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper


class BaseDatabaseClient:
    """Encapsulate backend-specific methods for opening a client shell."""

    # This should be a string representing the name of the executable
    # (e.g., "psql"). Subclasses must override this.
    executable_name = None

    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        # connection is an instance of BaseDatabaseWrapper.
        self.connection = connection

    @classmethod
    def settings_to_cmd_args_env(
        cls, settings_dict: dict[str, Any], parameters: list[str]
    ) -> tuple[list[str], dict[str, str] | None]:
        raise NotImplementedError(
            "subclasses of BaseDatabaseClient must provide a "
            "settings_to_cmd_args_env() method or override a runshell()."
        )

    def runshell(self, parameters: list[str]) -> None:
        args, env = self.settings_to_cmd_args_env(
            self.connection.settings_dict, parameters
        )
        env = {**os.environ, **env} if env else None
        subprocess.run(args, env=env, check=True)
