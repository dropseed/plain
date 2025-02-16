import os
import subprocess


class PostgresBackupClient:
    def __init__(self, connection):
        self.connection = connection

    def get_env(self):
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

    def create_backup(self, backup_path, *, pg_dump="pg_dump"):
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

    def restore_backup(self, backup_path, *, pg_restore="pg_restore"):
        settings_dict = self.connection.settings_dict

        args = pg_restore.split()
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

        args += ["--clean"]  # Drop existing tables
        args += ["-d", dbname]

        # Using stdin/stdout let's us use executables from within a docker container too
        args = ["gunzip", "<", str(backup_path), "|"] + args

        cmd = " ".join(args)

        subprocess.run(
            cmd, env={**os.environ, **self.get_env()}, check=True, shell=True
        )
