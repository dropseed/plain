from __future__ import annotations

import os

import click

from plain.cli.options import SettingOption


def _get_cpu_count() -> int:
    """Get the number of CPUs available, respecting cgroup limits in containers.

    os.process_cpu_count() only checks sched_getaffinity, not cgroup CPU quotas,
    so containers often see the host's full CPU count. This reads the cgroup v2
    quota file to detect the actual limit.

    Can be removed when minimum Python version is 3.14+ (cpython#120078).
    """
    cpu_count = os.process_cpu_count() or 1

    # Resolve the process's own cgroup path for nested cgroup v2 hierarchies
    # (e.g. systemd units, containers without a private cgroup namespace)
    cgroup_dir = "/sys/fs/cgroup"
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                # cgroup v2 entries have the form "0::<path>"
                parts = line.strip().split(":", 2)
                if (
                    len(parts) == 3
                    and parts[0] == "0"
                    and parts[1] == ""
                    and parts[2] != "/"
                ):
                    cgroup_dir = f"/sys/fs/cgroup{parts[2]}"
                    break
    except (FileNotFoundError, IndexError, OSError):
        pass

    # Check cgroup v2 CPU quota (Docker, Kubernetes, Railway, etc.)
    try:
        with open(f"{cgroup_dir}/cpu.max") as f:
            parts = f.read().strip().split()
            if len(parts) >= 2 and parts[0] != "max":
                quota = int(parts[0])
                period = int(parts[1])
                cgroup_cpus = max(1, -(-quota // period))  # ceiling division
                cpu_count = min(cpu_count, cgroup_cpus)
    except (FileNotFoundError, ValueError, OSError):
        pass

    return cpu_count


@click.command()
@click.option(
    "--bind",
    "-b",
    multiple=True,
    default=["127.0.0.1:8000"],
    help="Address to bind to (HOST:PORT, can be used multiple times)",
)
@click.option(
    "--threads",
    type=click.IntRange(min=1),
    cls=SettingOption,
    setting="SERVER_THREADS",
    help="Number of threads per worker",
)
@click.option(
    "--workers",
    "-w",
    type=int,
    cls=SettingOption,
    setting="SERVER_WORKERS",
    help="Number of worker processes (0=auto, based on CPU count)",
)
@click.option(
    "--timeout",
    "-t",
    type=int,
    cls=SettingOption,
    setting="SERVER_TIMEOUT",
    help="Worker timeout in seconds",
)
@click.option(
    "--certfile",
    type=click.Path(exists=True),
    help="SSL certificate file",
)
@click.option(
    "--keyfile",
    type=click.Path(exists=True),
    help="SSL key file",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Restart workers when code changes (dev only)",
)
@click.option(
    "--access-log/--no-access-log",
    cls=SettingOption,
    setting="SERVER_ACCESS_LOG",
    help="Enable/disable access logging to stdout",
)
def server(
    bind: tuple[str, ...],
    threads: int,
    workers: int,
    timeout: int,
    certfile: str | None,
    keyfile: str | None,
    reload: bool,
    access_log: bool,
) -> None:
    """Production-ready HTTP server"""
    from plain.runtime import settings

    # Show settings loaded from environment
    if env_settings := settings.get_env_settings():
        click.secho("Settings from env:", dim=True)
        for name, defn in env_settings:
            click.secho(
                f"  {defn.env_var_name} -> {name}={defn.display_value()}", dim=True
            )

    # 0 = auto (CPU count, cgroup-aware)
    if workers == 0:
        workers = _get_cpu_count()

    from plain.server import ServerApplication

    ServerApplication(
        bind=list(bind),
        threads=threads,
        workers=workers,
        timeout=timeout,
        reload=reload,
        certfile=certfile,
        keyfile=keyfile,
        accesslog=access_log,
    ).run()
