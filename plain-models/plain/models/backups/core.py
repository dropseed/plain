from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from plain.runtime import PLAIN_TEMP_PATH

from .. import db_connection as _db_connection
from .clients import PostgresBackupClient, SQLiteBackupClient


def get_git_branch() -> str | None:
    """Get current git branch, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def get_git_commit() -> str | None:
    """Get current git commit (short hash), or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper

# Cast for type checkers; runtime value is _db_connection (DatabaseConnection)
db_connection = cast("BaseDatabaseWrapper", _db_connection)


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

    def create(self, *, source: str = "manual", **create_kwargs: Any) -> Path:
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

        # Write metadata
        metadata = {
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "source": source,
            "git_branch": get_git_branch(),
            "git_commit": get_git_commit(),
        }
        metadata_path = self.path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        return self.path

    def restore(self, **restore_kwargs: Any) -> None:
        backup_file = self.path / "default.backup"

        if db_connection.vendor == "postgresql":
            PostgresBackupClient(db_connection).restore_backup(
                backup_file,
                pg_restore=restore_kwargs.get("pg_restore", "pg_restore"),
            )
        elif db_connection.vendor == "sqlite":
            SQLiteBackupClient(db_connection).restore_backup(backup_file)
        else:
            raise Exception("Unsupported database vendor")

    @property
    def metadata(self) -> dict[str, Any]:
        """Read metadata from metadata.json, with fallback for old backups."""
        metadata_path = self.path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                return json.load(f)

        return {
            "created_at": None,
            "source": None,
            "git_branch": None,
            "git_commit": None,
        }

    def delete(self) -> None:
        backup_file = self.path / "default.backup"
        backup_file.unlink()
        metadata_file = self.path / "metadata.json"
        if metadata_file.exists():
            metadata_file.unlink()
        self.path.rmdir()

    def updated_at(self) -> datetime.datetime:
        mtime = os.path.getmtime(self.path)
        return datetime.datetime.fromtimestamp(mtime)
