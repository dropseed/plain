from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from plain.runtime import PLAIN_TEMP_PATH

from .. import db_connection as _db_connection
from .clients import PostgresBackupClient


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
    from plain.models.postgres.wrapper import DatabaseWrapper

# Cast for type checkers; runtime value is _db_connection (DatabaseConnection)
db_connection = cast("DatabaseWrapper", _db_connection)


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
        try:
            self.prune()
        except Exception:
            pass
        return backup_dir

    def prune(self) -> list[str]:
        """Delete oldest backups on the current branch (or with no branch), keeping the most recent 20."""
        keep = 20
        current_branch = get_git_branch()
        backups = self.find_backups()  # sorted newest-first

        # Only prune backups matching the current branch or with no branch metadata
        prunable = [
            b for b in backups if b.metadata.get("git_branch") in (current_branch, None)
        ]

        deleted = []
        for backup in prunable[keep:]:
            backup.delete()
            deleted.append(backup.name)
        return deleted

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

        PostgresBackupClient(db_connection).create_backup(
            backup_path,
            pg_dump=create_kwargs.get("pg_dump", "pg_dump"),
        )

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

        PostgresBackupClient(db_connection).restore_backup(
            backup_file,
            pg_restore=restore_kwargs.get("pg_restore", "pg_restore"),
        )

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
        backup_file.unlink(missing_ok=True)
        metadata_file = self.path / "metadata.json"
        metadata_file.unlink(missing_ok=True)
        self.path.rmdir()

    def updated_at(self) -> datetime.datetime:
        mtime = os.path.getmtime(self.path)
        return datetime.datetime.fromtimestamp(mtime)
