import datetime
import os
from pathlib import Path

from plain.runtime import PLAIN_TEMP_PATH

from .. import connections
from .clients import PostgresBackupClient, SQLiteBackupClient


class DatabaseBackups:
    def __init__(self):
        self.path = PLAIN_TEMP_PATH / "backups"

    def find_backups(self):
        if not self.path.exists():
            return []

        backups = []

        for backup_dir in self.path.iterdir():
            backup = DatabaseBackup(backup_dir.name, backups_path=self.path)
            backups.append(backup)

        # Sort backups by date
        backups.sort(key=lambda x: x.updated_at(), reverse=True)

        return backups

    def create(self, name, **create_kwargs):
        backup = DatabaseBackup(name, backups_path=self.path)
        if backup.exists():
            raise Exception(f"Backup {name} already exists")
        backup_dir = backup.create(**create_kwargs)
        return backup_dir

    def restore(self, name, **restore_kwargs):
        backup = DatabaseBackup(name, backups_path=self.path)
        if not backup.exists():
            raise Exception(f"Backup {name} not found")
        backup.restore(**restore_kwargs)

    def delete(self, name):
        backup = DatabaseBackup(name, backups_path=self.path)
        if not backup.exists():
            raise Exception(f"Backup {name} not found")
        backup.delete()


class DatabaseBackup:
    def __init__(self, name: str, *, backups_path: Path):
        self.name = name
        self.path = backups_path / name

        if not self.name:
            raise ValueError("Backup name is required")

    def exists(self):
        return self.path.exists()

    def create(self, **create_kwargs):
        self.path.mkdir(parents=True, exist_ok=True)

        for connection_alias in connections:
            connection = connections[connection_alias]
            backup_path = self.path / f"{connection_alias}.backup"

            if connection.vendor == "postgresql":
                PostgresBackupClient(connection).create_backup(
                    backup_path,
                    pg_dump=create_kwargs.get("pg_dump", "pg_dump"),
                )
            elif connection.vendor == "sqlite":
                SQLiteBackupClient(connection).create_backup(backup_path)
            else:
                raise Exception("Unsupported database vendor")

        return self.path

    def iter_files(self):
        for backup_file in self.path.iterdir():
            if not backup_file.is_file():
                continue
            if not backup_file.name.endswith(".backup"):
                continue
            yield backup_file

    def restore(self, **restore_kwargs):
        for backup_file in self.iter_files():
            connection_alias = backup_file.stem
            connection = connections[connection_alias]
            if not connection:
                raise Exception(f"Connection {connection_alias} not found")

            if connection.vendor == "postgresql":
                PostgresBackupClient(connection).restore_backup(
                    backup_file,
                    pg_restore=restore_kwargs.get("pg_restore", "pg_restore"),
                )
            elif connection.vendor == "sqlite":
                SQLiteBackupClient(connection).restore_backup(backup_file)
            else:
                raise Exception("Unsupported database vendor")

    def delete(self):
        for backup_file in self.iter_files():
            backup_file.unlink()

        self.path.rmdir()

    def updated_at(self):
        mtime = os.path.getmtime(self.path)
        return datetime.datetime.fromtimestamp(mtime)
