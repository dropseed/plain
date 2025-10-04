from __future__ import annotations

import datetime
import os
from collections.abc import Generator
from pathlib import Path
from typing import Any

from plain.runtime import PLAIN_TEMP_PATH

from .. import db_connection
from .clients import PostgresBackupClient, SQLiteBackupClient


class DatabaseBackups:
    def __init__(self) -> None:
        self.path = PLAIN_TEMP_PATH / "backups"

    def find_backups(self) -> list[DatabaseBackup]:
        if not self.path.exists():
            return []

        backups = []

        for backup_dir in self.path.iterdir():
            backup = DatabaseBackup(backup_dir.name, backups_path=self.path)
            backups.append(backup)

        # Sort backups by date
        backups.sort(key=lambda x: x.updated_at(), reverse=True)

        return backups

    def create(self, name: str, **create_kwargs: Any) -> Path:
        backup = DatabaseBackup(name, backups_path=self.path)
        if backup.exists():
            raise Exception(f"Backup {name} already exists")
        backup_dir = backup.create(**create_kwargs)
        return backup_dir

    def restore(self, name: str, **restore_kwargs: Any) -> None:
        backup = DatabaseBackup(name, backups_path=self.path)
        if not backup.exists():
            raise Exception(f"Backup {name} not found")
        backup.restore(**restore_kwargs)

    def delete(self, name: str) -> None:
        backup = DatabaseBackup(name, backups_path=self.path)
        if not backup.exists():
            raise Exception(f"Backup {name} not found")
        backup.delete()


class DatabaseBackup:
    def __init__(self, name: str, *, backups_path: Path) -> None:
        self.name = name
        self.path = backups_path / name

        if not self.name:
            raise ValueError("Backup name is required")

    def exists(self) -> bool:
        return self.path.exists()

    def create(self, **create_kwargs: Any) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)

        backup_path = self.path / "default.backup"

        if db_connection.vendor == "postgresql":
            PostgresBackupClient(db_connection).create_backup(
                backup_path,
                pg_dump=create_kwargs.get("pg_dump", "pg_dump"),
            )
        elif db_connection.vendor == "sqlite":
            SQLiteBackupClient(db_connection).create_backup(backup_path)
        else:
            raise Exception("Unsupported database vendor")

        return self.path

    def iter_files(self) -> Generator[Path, None, None]:
        for backup_file in self.path.iterdir():
            if not backup_file.is_file():
                continue
            if not backup_file.name.endswith(".backup"):
                continue
            yield backup_file

    def restore(self, **restore_kwargs: Any) -> None:
        for backup_file in self.iter_files():
            if db_connection.vendor == "postgresql":
                PostgresBackupClient(db_connection).restore_backup(
                    backup_file,
                    pg_restore=restore_kwargs.get("pg_restore", "pg_restore"),
                )
            elif db_connection.vendor == "sqlite":
                SQLiteBackupClient(db_connection).restore_backup(backup_file)
            else:
                raise Exception("Unsupported database vendor")

    def delete(self) -> None:
        for backup_file in self.iter_files():
            backup_file.unlink()

        self.path.rmdir()

    def updated_at(self) -> datetime.datetime:
        mtime = os.path.getmtime(self.path)
        return datetime.datetime.fromtimestamp(mtime)
