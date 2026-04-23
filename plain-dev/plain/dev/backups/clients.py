from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from plain.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from plain.postgres.connection import DatabaseConnection


class PostgresBackupClient:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def _run(self, cmd: str | list[str], *, shell: bool = False) -> None:
        from plain.postgres.database_url import postgres_cli_env

        env = {**os.environ, **postgres_cli_env(self.connection.settings_dict)}
        subprocess.run(cmd, env=env, check=True, shell=shell)

    def create_backup(self, backup_path: Path, *, pg_dump: str = "pg_dump") -> None:
        from plain.postgres.database_url import postgres_cli_args

        settings_dict = self.connection.settings_dict
        dbname = settings_dict.get("DATABASE")
        if not dbname:
            raise ImproperlyConfigured("POSTGRES_DATABASE is required in settings")

        args = pg_dump.split() + postgres_cli_args(settings_dict)
        args += ["-Fc", dbname]

        # Pipe through gzip for compression
        args += ["|", "gzip", ">", str(backup_path)]
        self._run(" ".join(args), shell=True)

    def restore_backup(
        self, backup_path: Path, *, pg_restore: str = "pg_restore", psql: str = "psql"
    ) -> None:
        from plain.postgres.database_url import postgres_cli_args

        settings_dict = self.connection.settings_dict
        dbname = settings_dict.get("DATABASE")
        if not dbname:
            raise ImproperlyConfigured("POSTGRES_DATABASE is required in settings")

        conn_args = postgres_cli_args(settings_dict)

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
