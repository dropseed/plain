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

import json
import os
import re
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

    def server_command(
        self, *args: str, stdin: bool = False
    ) -> tuple[list[str], dict[str, str]]:
        """Argv + env to run a Postgres binary *where the server's binaries live*.

        For Docker that's inside the container (pass `stdin=True` when the
        command reads stdin, so `docker exec -i` attaches it), which guarantees
        `pg_dump`/`pg_restore` match the server version — the host may not have
        them at all. For a local server they're on the host by definition.
        """
        if self.container:
            argv = [
                "docker",
                "exec",
                *(["-i"] if stdin else []),
                "-e",
                f"PGPASSWORD={self.password}",
                self.container,
                *args,
            ]
            return argv, dict(os.environ)
        return [*args], {**os.environ, "PGPASSWORD": self.password}


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


@dataclass(frozen=True)
class ContainerState:
    """What one `docker inspect` tells us about an existing container."""

    running: bool
    image: str
    bound_host_ip: str  # "" means all interfaces
    host_port: int | None  # the assigned host port for 5432/tcp; None if not running
    max_connections: int | None  # from the `-c max_connections=N` launch arg


def _inspect_container(name: str) -> ContainerState | None:
    """Everything we ask about a container, in a single `docker` call.

    Each `docker` invocation costs ~100-300ms under Docker Desktop, and the
    questions (exists? running? which image? bound where? which port?) always
    travel together — separate probes made opening a cluster the slowest part
    of every `plain db` command.
    """
    result = _docker("inspect", name, check=False)
    if result.returncode != 0:
        return None  # no such container

    data = json.loads(result.stdout)[0]
    bindings = (data["HostConfig"].get("PortBindings") or {}).get("5432/tcp") or []

    # The *assigned* host port lives here once the container is running;
    # HostConfig.PortBindings only holds the requested "0" (pick one for me).
    published = (data["NetworkSettings"].get("Ports") or {}).get("5432/tcp") or []
    host_port = (
        int(published[0]["HostPort"])
        if published and published[0].get("HostPort")
        else None
    )

    # max_connections is fixed at creation via `-c max_connections=N`.
    cmd = data["Config"].get("Cmd") or []
    max_connections = None
    for i, arg in enumerate(cmd):
        if (
            arg == "-c"
            and i + 1 < len(cmd)
            and cmd[i + 1].startswith("max_connections=")
        ):
            max_connections = int(cmd[i + 1].split("=", 1)[1])
            break

    return ContainerState(
        running=data["State"]["Running"],
        image=data["Config"]["Image"],
        bound_host_ip=bindings[0].get("HostIp", "") if bindings else "",
        host_port=host_port,
        max_connections=max_connections,
    )


def _container_host_port(name: str) -> int:
    lines = _docker("port", name, "5432/tcp").stdout.strip().splitlines()
    if not lines:
        raise RuntimeError(
            f"Container {name!r} has no published port for 5432/tcp. "
            f"It wasn't created by plain-dev in its current form — recreate it: "
            f"docker rm -f {name}"
        )
    return int(lines[0].rsplit(":", 1)[1])


def _warn_if_container_drifted(
    container: str,
    state: ContainerState,
    *,
    image: str,
    max_connections: int,
) -> None:
    """Flag an existing container whose creation-time settings no longer match.

    Image, the localhost binding, and `max_connections` are all fixed when the
    container is created — changing them in code (or picking up a newer
    plain-dev) doesn't touch a container that already exists. We collect every
    drift and print the one shared remedy: recreate it. That's cheap, because
    the data lives on a separate volume and survives — except across a Postgres
    *major* version bump, where a dump and reload is needed instead.
    """
    lines: list[str] = []
    major_version_caution = False

    if state.image and state.image != image:
        lines.append(
            f"  Image is set to {image!r} but the running container was built "
            f"from {state.image!r}."
        )
        major_version_caution = True

    if state.bound_host_ip in ("", "0.0.0.0"):
        lines.append(
            "  It's published on all network interfaces, but the dev "
            "credentials are fixed — anyone on the same network can log in."
        )

    if state.max_connections is not None and state.max_connections != max_connections:
        lines.append(
            f"  max_connections is {state.max_connections}, code wants "
            f"{max_connections}."
        )

    if not lines:
        return

    click.secho(
        f"Postgres container {container!r} has drifted from its configuration:",
        fg="yellow",
        err=True,
    )
    for line in lines:
        click.echo(line, err=True)
    click.echo(
        f"  Recreate it to pick these up; your data is on a separate volume and "
        f"survives:\n"
        f"    docker rm -f {container}",
        err=True,
    )
    if major_version_caution:
        click.echo(
            "  If this is a different Postgres major version, back up first — a "
            "new major can't read the old data directory:\n"
            '    pg_dump -Fc "$(plain db url)" > backup.dump',
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

    Published as `-p 127.0.0.1:0:5432` so Docker picks a free host port — no
    port registry, no contention between projects — and binds it to localhost
    only. The credentials are fixed dev credentials (`postgres`/`postgres`), so
    the cluster must never be reachable from another machine on the network.
    The container is the durable handle; the port is read back from it.
    """
    state = _inspect_container(container)
    if state is None:
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
            "127.0.0.1:0:5432",
            image,
            # One cluster serves every worktree's pool plus xdist workers, so
            # PG's default of 100 runs out fast.
            "-c",
            f"max_connections={max_connections}",
        )
        port = _container_host_port(container)
    else:
        _warn_if_container_drifted(
            container, state, image=image, max_connections=max_connections
        )
        if state.running and state.host_port is not None:
            port = state.host_port  # already parsed from the inspect call
        else:
            if not state.running:
                _docker("start", container)
            # Ports is only populated once running, so read it back now.
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
    state = _inspect_container(container)
    if state is None or not state.running:
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


# The names `cluster_name()` produces: `plain-postgres-{project}-{8 hex}`.
# Docker's `--filter name=` is a substring match, so it happily returns
# containers we never created — a hand-rolled `plain-postgres-dev` from some
# older script matches too. Listing someone else's container as ours invites
# `plain db server remove` on it, so the shape is checked here.
MANAGED_CONTAINER_RE = re.compile(r"^plain-postgres-.+-[0-9a-f]{8}$")


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
        if not MANAGED_CONTAINER_RE.match(name):
            continue
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
    """Is there a local Postgres we can actually log into?

    An open port is not enough. Homebrew and Postgres.app — the two most common
    ways to have Postgres on a Mac — set up a superuser named after your OS
    account with trust auth and no `postgres` role at all. Treating "something
    is listening" as availability picked that server and then failed on every
    connection, with nothing saying why. So the probe is the real question:
    can we authenticate as the user we're going to use?
    """
    if not port_is_open(LOCAL_PORT):
        return False

    import psycopg

    try:
        psycopg.connect(
            host="127.0.0.1",
            port=LOCAL_PORT,
            user=DEV_USER,
            password=DEV_PASSWORD,
            dbname="postgres",
            connect_timeout=2,
        ).close()
    except psycopg.OperationalError:
        return False
    return True


def local_rejected_us() -> bool:
    """Is a local Postgres listening, but not one we can use?

    Distinguishes "you have no Postgres" from "you have one and we can't log
    into it" — different problems with different fixes, and only the second is
    worth telling someone their existing server is the reason.
    """
    return port_is_open(LOCAL_PORT) and not local_available()


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
