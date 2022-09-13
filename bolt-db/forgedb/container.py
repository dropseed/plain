import os
import re
import subprocess

import dj_database_url
from forgecore import Forge


class DBContainer:
    def __init__(self):
        forge = Forge()
        name = os.path.basename(forge.repo_root) + "-postgres"
        tmp_dir = forge.forge_tmp_dir

        self.name = name
        self.tmp_dir = os.path.abspath(tmp_dir)
        self.postgres_version = os.environ.get("POSTGRES_VERSION", "13")
        parsed_db_url = dj_database_url.parse(os.environ.get("DATABASE_URL"))
        self.postgres_port = parsed_db_url.get("PORT", "5432")
        self.postgres_db = parsed_db_url.get("NAME", "postgres")
        self.postgres_user = parsed_db_url.get("USER", "postgres")
        self.postgres_password = parsed_db_url.get("PASSWORD", "postgres")

    def start(self):
        try:
            subprocess.check_output(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.name,
                    "--rm",
                    "-e",
                    f"POSTGRES_DB={self.postgres_db}",
                    "-e",
                    f"POSTGRES_USER={self.postgres_user}",
                    "-e",
                    f"POSTGRES_PASSWORD={self.postgres_password}",
                    "-v",
                    f"{self.tmp_dir}/pgdata:/var/lib/postgresql/data",
                    "-p",
                    f"{self.postgres_port}:5432",
                    f"postgres:{self.postgres_version}",
                    "postgres",
                    "-c",
                    "stats_temp_directory=/tmp",
                ],
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            if "already in use" not in e.stderr.decode():
                raise

    def stop(self):
        try:
            subprocess.check_output(
                [
                    "docker",
                    "stop",
                    self.name,
                ],
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as e:
            if "No such container" not in e.stderr.decode():
                raise

    def logs(self):
        subprocess.check_call(
            [
                "docker",
                "logs",
                "--follow",
                "--tail",
                "5",
                self.name,
            ],
        )

    def execute(self, command, *args, **kwargs):
        docker_flags = kwargs.pop("docker_flags", "-it")
        return subprocess.run(
            [
                "docker",
                "exec",
                docker_flags,
                self.name,
                *command.split(),
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
                raise

        if create:
            self.execute(
                f"createdb {self.postgres_db} -U {self.postgres_user}",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

    def restore_dump(self, dump_path, compressed=False):
        """Imports a dump into {name}_import, then renames to {name} to prevent Django connections during process"""
        maintenance_db = "template1"
        import_db = f"{self.postgres_db}_import"

        self.execute(
            f"dropdb {import_db} --if-exists -U {self.postgres_user}",
            stdout=subprocess.DEVNULL,
        )
        self.execute(
            f"createdb {import_db} -U {self.postgres_user}", stdout=subprocess.DEVNULL
        )

        if compressed:
            restore_command = (
                f"pg_restore --no-owner --dbname {import_db} -U {self.postgres_user}"
            )
        else:
            # Text format can to straight in (has already gone through pg_restore to get text format)
            restore_command = f"psql {import_db} -U {self.postgres_user}"

        result = self.execute(
            restore_command,
            stdin=open(dump_path),
            docker_flags="-i",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.stderr:
            # Print errors except for role does not exist (can't ignore this in psql-style import)
            role_error_re = re.compile(r"^ERROR:  role \".+\" does not exist")
            for line in result.stderr.decode().splitlines():
                if not role_error_re.match(line):
                    print(line)

        # Get rid of the main database
        self.reset(create=False)

        # Connect to template1 (which should exist as "maintenance db") so we can rename the others
        self.execute(
            f"psql -U {self.postgres_user} {maintenance_db} -c",
            f"ALTER DATABASE {import_db} RENAME TO {self.postgres_db}",
            stdout=subprocess.DEVNULL,
        )
