import os
import platform
import socket
import subprocess
import sys
import tomllib
from importlib.metadata import entry_points
from importlib.util import find_spec
from pathlib import Path

import click
from rich.columns import Columns
from rich.console import Console
from rich.text import Text

from plain.runtime import APP_PATH, PLAIN_TEMP_PATH

from .mkcert import MkcertManager
from .process import ProcessManager
from .utils import has_pyproject_toml

ENTRYPOINT_GROUP = "plain.dev"


class DevProcess(ProcessManager):
    pidfile = PLAIN_TEMP_PATH / "dev" / "dev.pid"
    log_dir = PLAIN_TEMP_PATH / "dev" / "logs" / "run"

    def setup(
        self, *, port: int | None, hostname: str | None, log_level: str | None
    ) -> None:
        if not hostname:
            project_name = os.path.basename(
                os.getcwd()
            )  # Use directory name by default

            if has_pyproject_toml(APP_PATH.parent):
                with open(Path(APP_PATH.parent, "pyproject.toml"), "rb") as f:
                    pyproject = tomllib.load(f)
                    project_name = pyproject.get("project", {}).get(
                        "name", project_name
                    )

            hostname = f"{project_name.lower()}.localhost"

        self.hostname = hostname
        self.log_level = log_level

        self.pid_value = self.pid
        self.prepare_log()

        if port:
            self.port = int(port)
            if not self._port_available(self.port):
                click.secho(f"Port {self.port} in use", fg="red")
                raise SystemExit(1)
        else:
            self.port = self._find_open_port(8443)
            if self.port != 8443:
                click.secho(f"Port 8443 in use, using {self.port}", fg="yellow")

        self.ssl_key_path = None
        self.ssl_cert_path = None

        self.url = f"https://{self.hostname}:{self.port}"
        self.tunnel_url = os.environ.get("PLAIN_DEV_TUNNEL_URL", "")

        self.plain_env = {
            "PYTHONUNBUFFERED": "true",
            "PLAIN_DEV": "true",
            "FORCE_COLOR": "1",
            **os.environ,
        }

        if log_level:
            self.plain_env["PLAIN_FRAMEWORK_LOG_LEVEL"] = log_level.upper()
            self.plain_env["PLAIN_LOG_LEVEL"] = log_level.upper()

        self.custom_process_env = {
            **self.plain_env,
            "PORT": str(self.port),
            "PLAIN_DEV_URL": self.url,
        }

        if self.tunnel_url:
            status_bar = Columns(
                [
                    Text.from_markup(
                        f"[bold]Tunnel[/bold] [underline][link={self.tunnel_url}]{self.tunnel_url}[/link][/underline]"
                    ),
                    Text.from_markup(
                        f"[dim][bold]Server[/bold] [link={self.url}]{self.url}[/link][/dim]"
                    ),
                    Text.from_markup(
                        "[dim][bold]Ctrl+C[/bold] to stop[/dim]",
                        justify="right",
                    ),
                ],
                expand=True,
            )
        else:
            status_bar = Columns(
                [
                    Text.from_markup(
                        f"[bold]Server[/bold] [underline][link={self.url}]{self.url}[/link][/underline]"
                    ),
                    Text.from_markup(
                        "[dim][bold]Ctrl+C[/bold] to stop[/dim]", justify="right"
                    ),
                ],
                expand=True,
            )
        self.console = Console(markup=False, highlight=False)
        self.console_status = self.console.status(status_bar)

        self.init_poncho(self.console.out)

    def _find_open_port(self, start_port: int) -> int:
        port = start_port
        while not self._port_available(port):
            port += 1
        return port

    def _port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            result = sock.connect_ex(("127.0.0.1", port))
        return result != 0

    def run(self) -> int:
        self.write_pidfile()
        mkcert_manager = MkcertManager()
        mkcert_manager.setup_mkcert(install_path=Path.home() / ".plain" / "dev")
        self.ssl_cert_path, self.ssl_key_path = mkcert_manager.generate_certs(
            domain=self.hostname,
            storage_path=Path(PLAIN_TEMP_PATH) / "dev" / "certs",
        )

        self.symlink_plain_src()
        self.generate_agents_md()
        self.modify_hosts_file()

        click.secho("→ Running preflight checks... ", dim=True, nl=False)
        self.run_preflight()

        # if ServicesProcess.running_pid():
        #     self.poncho.add_process(
        #         "services",
        #         f"{sys.executable} -m plain dev logs --services --follow",
        #     )

        if find_spec("plain.models"):
            click.secho("→ Waiting for database... ", dim=True, nl=False)
            subprocess.run(
                [sys.executable, "-m", "plain", "db", "wait"],
                env=self.plain_env,
                check=True,
            )
            click.secho("→ Running migrations...", dim=True)
            subprocess.run(
                [sys.executable, "-m", "plain", "migrate", "--backup"],
                env=self.plain_env,
                check=True,
            )

        click.secho("\n→ Starting app...", dim=True)

        # Manually start the status bar now so it isn't bungled by
        # another thread checking db stuff...
        self.console_status.start()

        self.add_server()
        self.add_entrypoints()
        self.add_pyproject_run()

        try:
            # Start processes we know about and block the main thread
            self.poncho.loop()

            # Remove the status bar
            self.console_status.stop()
        finally:
            self.rm_pidfile()
            self.close()

        return self.poncho.returncode

    def symlink_plain_src(self) -> None:
        """Symlink the plain package into .plain so we can look at it easily"""
        spec = find_spec("plain.runtime")
        if spec is None or spec.origin is None:
            return None
        plain_path = Path(spec.origin).parent.parent
        if not PLAIN_TEMP_PATH.exists():
            PLAIN_TEMP_PATH.mkdir()

        symlink_path = PLAIN_TEMP_PATH / "src"

        # The symlink is broken
        if symlink_path.is_symlink() and not symlink_path.exists():
            symlink_path.unlink()

        # The symlink exists but points to the wrong place
        if (
            symlink_path.is_symlink()
            and symlink_path.exists()
            and symlink_path.resolve() != plain_path
        ):
            symlink_path.unlink()

        if plain_path.exists() and not symlink_path.exists():
            symlink_path.symlink_to(plain_path)

    def generate_agents_md(self) -> None:
        """Generate .plain/AGENTS.md from installed packages with AGENTS.md files."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "plain", "agent", "md", "--save"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 and result.stderr:
                click.secho(
                    f"Warning: Failed to generate .plain/AGENTS.md: {result.stderr}",
                    fg="yellow",
                    err=True,
                )
        except Exception as e:
            click.secho(
                f"Warning: Failed to generate .plain/AGENTS.md: {e}",
                fg="yellow",
                err=True,
            )

    def modify_hosts_file(self) -> None:
        """Modify the hosts file to map the custom domain to 127.0.0.1."""
        entry_identifier = "# Added by plain"
        hosts_entry = f"127.0.0.1 {self.hostname}  {entry_identifier}"

        if platform.system() == "Windows":
            hosts_path = Path(r"C:\Windows\System32\drivers\etc\hosts")
            try:
                with hosts_path.open("r") as f:
                    content = f.read()

                if hosts_entry in content:
                    return  # Entry already exists; no action needed

                # Entry does not exist; add it
                with hosts_path.open("a") as f:
                    f.write(f"{hosts_entry}\n")
                click.secho(f"Added {self.hostname} to {hosts_path}", bold=True)
            except PermissionError:
                click.secho(
                    "Permission denied while modifying hosts file. Please run the script as an administrator.",
                    fg="red",
                )
                sys.exit(1)
        else:
            # For macOS and Linux
            hosts_path = Path("/etc/hosts")
            try:
                with hosts_path.open("r") as f:
                    content = f.read()

                if hosts_entry in content:
                    return  # Entry already exists; no action needed

                # Entry does not exist; append it using sudo
                click.secho(
                    f"Adding {self.hostname} to /etc/hosts file. You may be prompted for your password.\n",
                    bold=True,
                )
                cmd = f"echo '{hosts_entry}' | sudo tee -a {hosts_path} >/dev/null"
                subprocess.run(cmd, shell=True, check=True)
                click.secho(f"Added {self.hostname} to {hosts_path}\n", bold=True)
            except PermissionError:
                click.secho(
                    "Permission denied while accessing hosts file.",
                    fg="red",
                )
                sys.exit(1)
            except subprocess.CalledProcessError:
                click.secho(
                    "Failed to modify hosts file. Please ensure you have sudo privileges.",
                    fg="red",
                )
                sys.exit(1)

    def run_preflight(self) -> None:
        if subprocess.run(
            ["plain", "preflight", "--quiet"], env=self.plain_env
        ).returncode:
            click.secho("Preflight check failed!", fg="red")
            sys.exit(1)

    def add_server(self) -> None:
        """Add the Plain HTTP server process."""
        server_cmd = [
            sys.executable,
            "-m",
            "plain",
            "server",
            "--bind",
            f"{self.hostname}:{self.port}",
            "--certfile",
            str(self.ssl_cert_path),
            "--keyfile",
            str(self.ssl_key_path),
            "--threads",
            "4",
            "--timeout",
            "60",
            "--log-level",
            self.log_level or "info",
            "--log-format",
            "'[%(levelname)s] %(message)s'",
            "--access-log-format",
            "'\"%(r)s\" status=%(s)s length=%(b)s time=%(M)sms'",
            "--reload",  # Enable auto-reload for development
        ]

        server = " ".join(server_cmd)
        self.poncho.add_process("plain", server, env=self.plain_env)

    def add_entrypoints(self) -> None:
        for entry_point in entry_points().select(group=ENTRYPOINT_GROUP):
            self.poncho.add_process(
                entry_point.name,
                f"plain dev entrypoint {entry_point.name}",
                env=self.plain_env,
            )

    def add_pyproject_run(self) -> None:
        """Additional processes that only run during `plain dev`."""
        if not has_pyproject_toml(APP_PATH.parent):
            return

        with open(Path(APP_PATH.parent, "pyproject.toml"), "rb") as f:
            pyproject = tomllib.load(f)

        run_commands = (
            pyproject.get("tool", {}).get("plain", {}).get("dev", {}).get("run", {})
        )
        for name, data in run_commands.items():
            env = {
                **self.custom_process_env,
                **data.get("env", {}),
            }
            self.poncho.add_process(name, data["cmd"], env=env)
