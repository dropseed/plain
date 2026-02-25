from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from plain.models.postgres.wrapper import DatabaseWrapper


class PostgresBackupClient:
    def __init__(self, connection: DatabaseWrapper) -> None:
        self.connection = connection

    def get_env(self) -> dict[str, str]:
        settings_dict = self.connection.settings_dict
        options = settings_dict.get("OPTIONS", {})
        env: dict[str, str] = {}

        if password := settings_dict.get("PASSWORD"):
            env["PGPASSWORD"] = str(password)

        # Map OPTIONS keys to their corresponding environment variables.
        option_env_vars = {
            "passfile": "PGPASSFILE",
            "sslmode": "PGSSLMODE",
            "sslrootcert": "PGSSLROOTCERT",
            "sslcert": "PGSSLCERT",
            "sslkey": "PGSSLKEY",
        }
        for option_key, env_var in option_env_vars.items():
            if value := options.get(option_key):
                env[env_var] = str(value)

        return env

    def _get_conn_args(self) -> list[str]:
        """Build common connection CLI args from settings."""
        settings_dict = self.connection.settings_dict
        args: list[str] = []
        if user := settings_dict.get("USER"):
            args += ["-U", user]
        if host := settings_dict.get("HOST"):
            args += ["-h", host]
        if port := settings_dict.get("PORT"):
            args += ["-p", str(port)]
        return args

    def _run(self, cmd: str | list[str], *, shell: bool = False) -> None:
        subprocess.run(
            cmd, env={**os.environ, **self.get_env()}, check=True, shell=shell
        )

    def create_backup(self, backup_path: Path, *, pg_dump: str = "pg_dump") -> None:
        settings_dict = self.connection.settings_dict
        dbname = settings_dict.get("DATABASE")
        if not dbname:
            raise ImproperlyConfigured("POSTGRES_DATABASE is required in settings")

        args = pg_dump.split() + self._get_conn_args()
        args += ["-Fc", dbname]

        # Pipe through gzip for compression
        args += ["|", "gzip", ">", str(backup_path)]
        self._run(" ".join(args), shell=True)

    def restore_backup(
        self, backup_path: Path, *, pg_restore: str = "pg_restore", psql: str = "psql"
    ) -> None:
        settings_dict = self.connection.settings_dict
        dbname = settings_dict.get("DATABASE")
        if not dbname:
            raise ImproperlyConfigured("POSTGRES_DATABASE is required in settings")

        conn_args = self._get_conn_args()

        # Drop and recreate the database via template1
        drop_create_cmds = [
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{dbname}' AND pid <> pg_backend_pid()",
            f'DROP DATABASE IF EXISTS "{dbname}"',
            f'CREATE DATABASE "{dbname}"',
        ]
        for sql in drop_create_cmds:
            self._run(psql.split() + conn_args + ["-d", "template1", "-c", sql])

        # Restore into the fresh database
        args = pg_restore.split() + conn_args + ["-d", dbname]

        # Pipe through gunzip for decompression
        args = ["gunzip", "<", str(backup_path), "|"] + args
        self._run(" ".join(args), shell=True)
