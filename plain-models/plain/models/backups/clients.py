from __future__ import annotations

import gzip
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper


class PostgresBackupClient:
    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        self.connection = connection

    def get_env(self) -> dict[str, str]:
        settings_dict = self.connection.settings_dict
        options = settings_dict.get("OPTIONS", {})
        env = {}
        if options.get("passfile"):
            env["PGPASSFILE"] = str(options.get("passfile"))
        if settings_dict.get("PASSWORD"):
            env["PGPASSWORD"] = str(settings_dict.get("PASSWORD"))
        if options.get("service"):
            env["PGSERVICE"] = str(options.get("service"))
        if options.get("sslmode"):
            env["PGSSLMODE"] = str(options.get("sslmode"))
        if options.get("sslrootcert"):
            env["PGSSLROOTCERT"] = str(options.get("sslrootcert"))
        if options.get("sslcert"):
            env["PGSSLCERT"] = str(options.get("sslcert"))
        if options.get("sslkey"):
            env["PGSSLKEY"] = str(options.get("sslkey"))
        return env

    def create_backup(self, backup_path: Path, *, pg_dump: str = "pg_dump") -> None:
        settings_dict = self.connection.settings_dict

        args = pg_dump.split()
        options = settings_dict.get("OPTIONS", {})

        host = settings_dict.get("HOST")
        port = settings_dict.get("PORT")
        dbname = settings_dict.get("NAME")
        user = settings_dict.get("USER")
        service = options.get("service")

        if not dbname and not service:
            # Connect to the default 'postgres' db.
            dbname = "postgres"
        if user:
            args += ["-U", user]
        if host:
            args += ["-h", host]
        if port:
            args += ["-p", str(port)]

        args += ["-Fc"]
        # args += ["-f", backup_path]

        if dbname:
            args += [dbname]

        # Using stdin/stdout let's us use executables from within a docker container too
        args += ["|", "gzip", ">", str(backup_path)]

        cmd = " ".join(args)

        subprocess.run(
            cmd, env={**os.environ, **self.get_env()}, check=True, shell=True
        )

    def restore_backup(
        self, backup_path: Path, *, pg_restore: str = "pg_restore", psql: str = "psql"
    ) -> None:
        settings_dict = self.connection.settings_dict

        host = settings_dict.get("HOST")
        port = settings_dict.get("PORT")
        dbname = settings_dict.get("NAME")
        user = settings_dict.get("USER")

        # Build common connection args
        conn_args = []
        if user:
            conn_args += ["-U", user]
        if host:
            conn_args += ["-h", host]
        if port:
            conn_args += ["-p", str(port)]

        # First, drop and recreate the database
        # Connect to 'template1' database to do this (works for all databases including 'postgres')
        drop_create_cmds = [
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{dbname}' AND pid <> pg_backend_pid()",
            f'DROP DATABASE IF EXISTS "{dbname}"',
            f'CREATE DATABASE "{dbname}"',
        ]

        for cmd in drop_create_cmds:
            psql_args = (
                psql.split()
                + conn_args
                + [
                    "-d",
                    "template1",  # Always use template1
                    "-c",
                    cmd,
                ]
            )
            subprocess.run(psql_args, env={**os.environ, **self.get_env()}, check=True)

        # Now restore into the fresh database
        args = pg_restore.split()
        args += conn_args
        args += ["-d", dbname]

        # Using stdin/stdout let's us use executables from within a docker container too
        args = ["gunzip", "<", str(backup_path), "|"] + args

        cmd = " ".join(args)

        subprocess.run(
            cmd, env={**os.environ, **self.get_env()}, check=True, shell=True
        )


class SQLiteBackupClient:
    def __init__(self, connection: BaseDatabaseWrapper) -> None:
        self.connection = connection

    def create_backup(self, backup_path: Path) -> None:
        self.connection.ensure_connection()
        src_conn = self.connection.connection
        dump = "\n".join(src_conn.iterdump())
        with gzip.open(backup_path, "wt") as f:
            f.write(dump)

    def restore_backup(self, backup_path: Path) -> None:
        with gzip.open(backup_path, "rt") as f:
            sql = f.read()

        self.connection.close()
        self.connection.connect()
        dest_conn = self.connection.connection
        cur = dest_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for (name,) in cur.fetchall():
            if not name.startswith("sqlite_"):
                dest_conn.execute(f'DROP TABLE IF EXISTS "{name}"')
        dest_conn.executescript(sql)
        dest_conn.commit()
