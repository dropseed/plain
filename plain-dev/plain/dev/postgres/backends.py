"""Where the managed Postgres server actually comes from.

Two backends, chosen in this order when `backend = "auto"`:

1. **Docker** — a container per project. Preferred on a workstation: the PG
   version is pinnable, data is isolated per project, and nothing contends for
   port 5432.
2. **Local** — a Postgres already listening on 127.0.0.1:5432. This is the
   path that makes remote/agent sandboxes work, where a Docker daemon usually
   isn't available but a system Postgres often is. Databases stay namespaced by
   project, so sharing one cluster is safe even though it's less isolated.

If neither is available we return `None` and say why. Never start a Docker
daemon, and never install Postgres.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from dataclasses import dataclass

import click

from .identity import DEV_PASSWORD, DEV_USER

LOCAL_PORT = 5432


@dataclass(frozen=True)
class Server:
    """A reachable Postgres server we can create databases on."""

    host: str
    port: int
    user: str
    password: str
    backend: str  # "docker" | "local"
    container: str | None = None  # set for the docker backend

    def url(self, db_name: str) -> str:
        return (
            f"postgres://{self.user}:{self.password}@{self.host}:{self.port}/{db_name}"
        )

    @property
    def internal_port(self) -> int:
        """The port Postgres listens on *from where its binaries run*.

        Inside a container that's always 5432 regardless of what Docker
        published on the host; for a local server it's the host port.
        """
        return 5432 if self.container else self.port

    def run_server_shell(self, command: str) -> subprocess.CompletedProcess[str]:
        """Run a shell command *where the Postgres binaries live*.

        For Docker that's inside the container, which guarantees `pg_dump` and
        `pg_restore` match the server version — the host may not have them at
        all. For a local server they're on the host by definition.
        """
        env_prefix = f"PGPASSWORD={self.password} "
        if self.container:
            return subprocess.run(
                [
                    "docker",
                    "exec",
                    "-e",
                    f"PGPASSWORD={self.password}",
                    self.container,
                    "sh",
                    "-c",
                    command,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        return subprocess.run(
            ["sh", "-c", env_prefix + command],
            capture_output=True,
            text=True,
            check=True,
        )


def port_is_open(port: int, *, host: str = "127.0.0.1", timeout: float = 0.25) -> bool:
    """Is something listening? ~0.2ms locally, so it's free to call on any command."""
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
        except OSError:
            return False
        return True


# --------------------------------------------------------------------------
# Docker
# --------------------------------------------------------------------------


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check
    )


def docker_available() -> bool:
    """Is the Docker CLI present *and* the daemon responding?"""
    if not shutil.which("docker"):
        return False
    try:
        return _docker("info", check=False).returncode == 0
    except OSError:
        return False


def _container_exists(name: str) -> bool:
    return bool(_docker("ps", "-aq", "-f", f"name=^{name}$").stdout.strip())


def _container_running(name: str) -> bool:
    return bool(_docker("ps", "-q", "-f", f"name=^{name}$").stdout.strip())


def _container_host_port(name: str) -> int:
    out = _docker("port", name, "5432/tcp").stdout.strip().splitlines()[0]
    return int(out.rsplit(":", 1)[1])


def _container_image(name: str) -> str:
    result = _docker("inspect", "--format", "{{.Config.Image}}", name, check=False)
    return result.stdout.strip()


def _warn_if_image_changed(container: str, image: str) -> None:
    """Say so when the configured image no longer matches the running one.

    Changing `image` in pyproject.toml doesn't rebuild an existing container —
    the image is fixed when it's created. Recreating is usually what you want
    (the data volume is separate and survives), but not always: a different
    Postgres *major* version can't read an existing data directory, so it needs
    a dump and reload rather than a new container. We can't tell those apart
    from a tag, so we say what changed and let you pick.
    """
    running = _container_image(container)
    if not running or running == image:
        return

    click.secho(
        f"Postgres image is set to {image!r} but the running container was "
        f"built from {running!r}.",
        fg="yellow",
        err=True,
    )
    click.echo(
        f"  Same Postgres major version (adding an extension, say)? Recreate it; "
        f"your data is on a separate volume and survives:\n"
        f"    docker rm -f {container}\n"
        f"  Different major version? Back up first — a new major can't read the "
        f"old data directory:\n"
        f"    plain dev backups create",
        err=True,
    )


def _create_container(*args: str) -> None:
    """`docker run`, tolerating another process having just done the same.

    Several worktrees of one project share a container, so two of them starting
    together will both find it missing and both try to create it. The loser gets
    a name conflict — which means the container it wanted now exists, so there is
    nothing to report.
    """
    try:
        _docker(*args)
    except subprocess.CalledProcessError as e:
        if "already in use" not in (e.stderr or ""):
            raise


def start_docker_server(
    *, container: str, volume: str, image: str, max_connections: int
) -> Server:
    """Ensure the project's container is running and return how to reach it.

    Published as `-p 0:5432` so Docker picks a free host port — no port
    registry, no contention between projects. The container is the durable
    handle; the port is read back from it.
    """
    if not _container_exists(container):
        _create_container(
            "run",
            "-d",
            "--name",
            container,
            # Deliberately no restart policy. A stopped container is started on
            # demand (~2s) by the branch below, so auto-starting every project's
            # Postgres at every boot would only buy those couple of seconds — at
            # a cost of ~76MB of RAM per project, permanently, for projects you
            # may not have touched in months.
            "-e",
            f"POSTGRES_USER={DEV_USER}",
            "-e",
            f"POSTGRES_PASSWORD={DEV_PASSWORD}",
            "-v",
            f"{volume}:/var/lib/postgresql/data",
            "-p",
            "0:5432",
            image,
            # One cluster serves every worktree's pool plus xdist workers, so
            # PG's default of 100 runs out fast. See DECISIONS D10.
            "-c",
            f"max_connections={max_connections}",
        )
    else:
        _warn_if_image_changed(container, image)
        if not _container_running(container):
            _docker("start", container)

    port = _container_host_port(container)
    wait_until_ready(port)
    return Server(
        host="127.0.0.1",
        port=port,
        user=DEV_USER,
        password=DEV_PASSWORD,
        backend="docker",
        container=container,
    )


def stop_container(container: str) -> bool:
    """Stop the container. Returns False if it wasn't running."""
    if not _container_running(container):
        return False
    _docker("stop", container, check=False)
    return True


def remove_container(container: str, *, volume: str | None = None) -> None:
    """Remove the container, and optionally the volume holding its data."""
    _docker("rm", "-f", container, check=False)
    if volume:
        _docker("volume", "rm", volume, check=False)


@dataclass(frozen=True)
class ManagedContainer:
    """A Postgres container plain-dev created, on this machine."""

    name: str
    running: bool
    image: str
    size: str


def list_managed_containers() -> list[ManagedContainer]:
    """Every plain-dev Postgres container here, not just this project's.

    Containers are per project, so they accumulate as you work on more of them.
    Nothing removes one automatically — a container we can't reach the project
    for might still hold the only copy of something — so this exists to make the
    pile visible rather than to guess at it.
    """
    result = _docker(
        "ps",
        "-a",
        "--filter",
        "name=plain-postgres-",
        "--format",
        "{{.Names}}\t{{.State}}\t{{.Image}}\t{{.Size}}",
        check=False,
    )
    containers = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 4:
            continue
        name, state, image, size = parts
        containers.append(
            ManagedContainer(
                name=name, running=state == "running", image=image, size=size
            )
        )
    return sorted(containers, key=lambda c: c.name)


# --------------------------------------------------------------------------
# Local
# --------------------------------------------------------------------------


def local_available() -> bool:
    return port_is_open(LOCAL_PORT)


def connect_local_server() -> Server:
    """Use a Postgres already running on 5432.

    Credentials are the conventional `postgres`/`postgres`; if the local server
    wants something else, that's a bring-your-own case and the user should set
    `PLAIN_POSTGRES_URL` instead.
    """
    return Server(
        host="127.0.0.1",
        port=LOCAL_PORT,
        user=DEV_USER,
        password=DEV_PASSWORD,
        backend="local",
    )


# --------------------------------------------------------------------------
# Readiness
# --------------------------------------------------------------------------


def wait_until_ready(port: int, *, timeout: float = 60.0) -> None:
    """Block until Postgres accepts a real connection, not just a TCP handshake.

    A fresh container listens on the port well before `initdb` finishes, so the
    TCP probe alone would hand back a server that refuses queries.
    """
    import psycopg

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            psycopg.connect(
                host="127.0.0.1",
                port=port,
                user=DEV_USER,
                password=DEV_PASSWORD,
                dbname="postgres",
                connect_timeout=2,
            ).close()
            return
        except psycopg.OperationalError as e:
            last_error = e
            time.sleep(0.5)

    raise TimeoutError(
        f"Postgres on port {port} did not become ready within {timeout:.0f}s: {last_error}"
    )
