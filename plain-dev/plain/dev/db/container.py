import os
import shlex
import subprocess

from plain.runtime import APP_PATH, settings

SNAPSHOT_DB_PREFIX = "plaindb_snapshot_"


class DBContainer:
    def __init__(self):
        project_root = APP_PATH.parent
        tmp_dir = settings.PLAIN_TEMP_PATH

        name = os.path.basename(project_root) + "-postgres-1"

        if "DATABASE_URL" in os.environ:
            from plain.models import database_url

            postgres_version = os.environ.get("POSTGRES_VERSION")
            parsed_db_url = database_url.parse(os.environ.get("DATABASE_URL"))

        self.name = name
        self.tmp_dir = os.path.abspath(tmp_dir)
        self.postgres_version = postgres_version or "13"
        self.postgres_port = parsed_db_url.get("PORT", "5432")
        self.postgres_db = parsed_db_url.get("NAME", "postgres")
        self.postgres_user = parsed_db_url.get("USER", "postgres")
        self.postgres_password = parsed_db_url.get("PASSWORD", "postgres")

    def execute(self, command, *args, **kwargs):
        docker_flags = kwargs.pop("docker_flags", "-it")
        return subprocess.run(
            [
                "docker",
                "exec",
                docker_flags,
                self.name,
                *shlex.split(command),
            ]
            + list(args),
            check=True,
            **kwargs,
        )

    def reset(self, create=False):
        try:
            self.execute(
                f"dropdb {self.postgres_db} --force -U {self.postgres_user}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            if "does not exist" not in e.stdout.decode():
                print(e.stderr.decode())
                raise

        if create:
            self.execute(
                f"createdb {self.postgres_db} -U {self.postgres_user}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def terminate_connections(self):
        self.execute(
            f"psql -U {self.postgres_user} {self.postgres_db} -c",
            f"SELECT pg_terminate_backend(pg_stat_activity.pid) FROM pg_stat_activity WHERE pg_stat_activity.datname = '{self.postgres_db}' AND pid <> pg_backend_pid();",
            stdout=subprocess.DEVNULL,
        )

    def create_snapshot(self, name):
        snapshot_name = f"{SNAPSHOT_DB_PREFIX}{name}"
        current_git_branch = (
            subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"])
            .decode()
            .strip()
        )
        description = f"branch={current_git_branch}"

        self.terminate_connections()
        try:
            self.execute(
                f"createdb {snapshot_name} '{description}' -U {self.postgres_user} -T {self.postgres_db}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            if "already exists" in e.stdout.decode():
                return False
            else:
                raise

        return True

    def list_snapshots(self):
        self.execute(
            f"psql -U {self.postgres_user} {self.postgres_db} -c",
            f"SELECT REPLACE(datname, '{SNAPSHOT_DB_PREFIX}', '') as name, pg_size_pretty(pg_database_size(datname)) as size, pg_catalog.shobj_description(oid, 'pg_database') AS description, (pg_stat_file('base/'||oid ||'/PG_VERSION')).modification as created FROM pg_catalog.pg_database WHERE datname LIKE '{SNAPSHOT_DB_PREFIX}%' ORDER BY created;",
        )

    def delete_snapshot(self, name):
        snapshot_name = f"{SNAPSHOT_DB_PREFIX}{name}"
        try:
            self.execute(
                f"dropdb {snapshot_name} -U {self.postgres_user}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            if "does not exist" in e.stdout.decode():
                return False
            else:
                raise

        return True

    def restore_snapshot(self, name):
        snapshot_name = f"{SNAPSHOT_DB_PREFIX}{name}"
        self.reset(create=False)
        self.execute(
            f"createdb {self.postgres_db} -U {self.postgres_user} -T {snapshot_name}",
        )

    def export(self, export_path):
        successful = (
            subprocess.run(
                [
                    "docker",
                    "exec",
                    self.name,
                    "/bin/bash",
                    "-c",
                    f"pg_dump -U {self.postgres_user} {self.postgres_db}",
                ],
                stdout=open(export_path, "w+"),
            ).returncode
            == 0
        )
        return successful

    def import_sql(self, sql_file):
        self.reset(create=True)
        successful = (
            subprocess.run(
                f"docker exec -i {self.name} psql -U {self.postgres_user} {self.postgres_db} < {shlex.quote(sql_file)}",
                shell=True,
            ).returncode
            == 0
        )
        return successful
