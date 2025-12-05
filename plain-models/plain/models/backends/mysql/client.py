from __future__ import annotations

import signal
from typing import TYPE_CHECKING

from plain.models.backends.base.client import BaseDatabaseClient

if TYPE_CHECKING:
    from plain.models.connections import DatabaseConfig


class DatabaseClient(BaseDatabaseClient):
    executable_name = "mysql"

    @classmethod
    def settings_to_cmd_args_env(
        cls, settings_dict: DatabaseConfig, parameters: list[str]
    ) -> tuple[list[str], dict[str, str] | None]:
        args = [cls.executable_name]
        env = None
        options = settings_dict.get("OPTIONS", {})
        database = options.get(
            "database",
            options.get("db", settings_dict.get("NAME")),
        )
        user = options.get("user", settings_dict.get("USER"))
        password = options.get(
            "password",
            options.get("passwd", settings_dict.get("PASSWORD")),
        )
        host = options.get("host", settings_dict.get("HOST"))
        port = options.get("port", settings_dict.get("PORT"))
        server_ca = options.get("ssl", {}).get("ca")
        client_cert = options.get("ssl", {}).get("cert")
        client_key = options.get("ssl", {}).get("key")
        defaults_file = options.get("read_default_file")
        charset = options.get("charset")
        # Seems to be no good way to set sql_mode with CLI.

        if defaults_file:
            args += [f"--defaults-file={defaults_file}"]
        if user:
            args += [f"--user={user}"]
        if password:
            # The MYSQL_PWD environment variable usage is discouraged per
            # MySQL's documentation due to the possibility of exposure through
            # `ps` on old Unix flavors but --password suffers from the same
            # flaw on even more systems. Usage of an environment variable also
            # prevents password exposure if the subprocess.run(check=True) call
            # raises a CalledProcessError since the string representation of
            # the latter includes all of the provided `args`.
            env = {"MYSQL_PWD": password}
        if host:
            if "/" in host:
                args += [f"--socket={host}"]
            else:
                args += [f"--host={host}"]
        if port:
            args += [f"--port={port}"]
        if server_ca:
            args += [f"--ssl-ca={server_ca}"]
        if client_cert:
            args += [f"--ssl-cert={client_cert}"]
        if client_key:
            args += [f"--ssl-key={client_key}"]
        if charset:
            args += [f"--default-character-set={charset}"]
        if database:
            args += [database]
        args.extend(parameters)
        return args, env

    def runshell(self, parameters: list[str]) -> None:
        sigint_handler = signal.getsignal(signal.SIGINT)
        try:
            # Allow SIGINT to pass to mysql to abort queries.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            super().runshell(parameters)
        finally:
            # Restore the original SIGINT handler.
            signal.signal(signal.SIGINT, sigint_handler)
