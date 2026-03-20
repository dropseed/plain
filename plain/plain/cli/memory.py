from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

from .runtime import without_runtime_setup

_BASELINE_SCRIPT = Path(__file__).with_name("_memory_baseline.py")

_DEFAULT_DURATION = 30


def _fmt(size_bytes: int) -> str:
    abs_size = abs(size_bytes)
    sign = "+" if size_bytes > 0 else ""
    if abs_size >= 1024 * 1024:
        return f"{sign}{size_bytes / (1024 * 1024):.1f} MB"
    if abs_size >= 1024:
        return f"{sign}{size_bytes / 1024:.1f} KB"
    return f"{sign}{size_bytes} B"


@without_runtime_setup
@click.group()
def memory() -> None:
    """Profile memory usage."""


@memory.command()
def baseline() -> None:
    """Show boot-time memory baseline.

    Measures which packages consume the most memory when a worker
    process starts — before any requests are handled.
    """
    result = subprocess.run(
        [sys.executable, str(_BASELINE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        click.secho("Failed to measure baseline:", fg="red", err=True)
        if result.stderr:
            click.echo(result.stderr, err=True)
        raise SystemExit(1)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        click.secho("Failed to parse baseline output:", fg="red", err=True)
        click.echo(result.stdout, err=True)
        raise SystemExit(1)

    click.echo(f"Worker RSS: {data['rss']:.0f} MB ({data['modules']} modules)")
    click.echo()

    if data["packages"]:
        click.secho("Heaviest packages:", fg="yellow", bold=True)
        for pkg, size_mb in data["packages"]:
            click.echo(f"  {pkg:30s} {size_mb:>6.1f} MB")


@memory.command()
@click.option(
    "--duration",
    type=int,
    default=_DEFAULT_DURATION,
    show_default=True,
    help="Recording duration in seconds (split into two halves automatically).",
)
@click.option(
    "--pid",
    type=int,
    default=None,
    help="Server arbiter PID (auto-detected if not specified).",
)
def leaks(duration: int, pid: int | None) -> None:
    """Check the running server for memory leaks.

    Records allocations in two phases and compares them.
    Only allocations that grew in BOTH phases are reported,
    filtering out one-time initialization noise.

    Send traffic to your app while the recording runs.
    """
    if duration < 4:
        click.secho("Duration must be at least 4 seconds.", fg="red", err=True)
        raise SystemExit(1)

    arbiter_pid = pid or _find_arbiter_pid()
    if not arbiter_pid:
        click.secho(
            "No running server found.\n"
            "Start the server with `plain dev` or `plain server` first.",
            fg="red",
            err=True,
        )
        raise SystemExit(1)

    worker_pids = _get_worker_pids(arbiter_pid)
    if not worker_pids:
        click.secho("No server workers found.", fg="red", err=True)
        raise SystemExit(1)

    half = duration // 2
    click.secho(
        f"Checking for leaks ({duration}s, {len(worker_pids)} worker(s))",
        bold=True,
    )
    click.echo("Send traffic to your app while this runs.")
    click.echo()

    try:
        # Signal 1: start recording
        _signal_arbiter(arbiter_pid)
        click.echo(f"  Phase 1/2 ({half}s)...", nl=False)
        time.sleep(half)
        click.echo(" done")

        # Signal 2: midpoint snapshot
        _signal_arbiter(arbiter_pid)
        click.echo(f"  Phase 2/2 ({duration - half}s)...", nl=False)
        time.sleep(duration - half)
        click.echo(" done")

        # Signal 3: stop and write results
        _signal_arbiter(arbiter_pid)
    except KeyboardInterrupt:
        click.echo()
        click.secho(
            "Interrupted — recording will auto-stop after 5 minutes.",
            fg="yellow",
            err=True,
        )
        raise SystemExit(1)

    # Give workers a moment to write output
    time.sleep(1)

    # Collect results from all workers
    from plain.server.workers._memory import profile_path

    results = []
    for wpid in worker_pids:
        output_path = Path(profile_path(wpid))
        try:
            results.append(json.loads(output_path.read_text()))
            output_path.unlink()
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    if not results:
        click.secho("No results collected.", fg="red", err=True)
        raise SystemExit(1)

    _display_results(results)


def _short_path(path: str) -> str:
    """Shorten an absolute path to something readable.

    site-packages/jinja2/env.py → jinja2/env.py
    /home/user/myapp/app/views.py → app/views.py
    plain/plain/utils/foo.py → plain/utils/foo.py
    """
    # Strip site-packages prefix → package/module.py
    if "site-packages/" in path:
        return path.split("site-packages/")[-1]

    # Strip up to a known source root
    for marker in ("/plain/plain/", "/plain-", "/app/", "/src/"):
        idx = path.find(marker)
        if idx != -1:
            return path[idx + 1 :]

    # Last resort: last 3 path components
    parts = path.rsplit("/", 3)
    return "/".join(parts[-3:]) if len(parts) > 3 else path


def _display_results(results: list[dict]) -> None:
    """Aggregate and display results from all workers."""
    total_rss_before = sum(r["rss_before"] for r in results)
    total_rss_after = sum(r["rss_after"] for r in results)
    rss_delta = total_rss_after - total_rss_before

    click.echo()

    # RSS summary (values are in bytes)
    mb = 1024 * 1024
    rss_delta_mb = rss_delta / mb
    rss_color = (
        "red" if rss_delta_mb > 1 else ("yellow" if rss_delta_mb > 0.1 else "green")
    )
    click.echo(
        f"  RSS: {total_rss_before / mb:.0f} MB → {total_rss_after / mb:.0f} MB ",
        nl=False,
    )
    click.secho(f"({_fmt(rss_delta)})", fg=rss_color)

    # Collect all leaks from all workers (the three-snapshot intersection
    # already filtered one-time init — everything here grew in both halves)
    all_leaks: list[dict] = []
    for r in results:
        all_leaks.extend(r["leaks"])

    if not all_leaks:
        click.echo()
        click.secho("  No leaks detected.", fg="green", bold=True)
        return

    # Group by file, track both phase sizes for trend display
    by_file: dict[str, dict] = {}
    for leak in all_leaks:
        fn = leak["file"]
        if fn not in by_file:
            by_file[fn] = {"size": 0, "lines": {}}
        by_file[fn]["size"] += leak["size_second"]
        line = leak["line"]
        if line not in by_file[fn]["lines"]:
            by_file[fn]["lines"][line] = {"first": 0, "second": 0}
        by_file[fn]["lines"][line]["first"] += leak["size_first"]
        by_file[fn]["lines"][line]["second"] += leak["size_second"]

    click.echo()
    click.secho("Suspected leaks:", fg="yellow", bold=True)
    ranked = sorted(by_file.items(), key=lambda x: x[1]["size"], reverse=True)
    for fn, info in ranked[:10]:
        short = _short_path(fn)
        click.echo(f"  {short}")
        top_lines = sorted(
            info["lines"].items(), key=lambda x: x[1]["second"], reverse=True
        )
        for line, sizes in top_lines[:3]:
            click.echo(
                f"    line {line}: {_fmt(sizes['first'])} → {_fmt(sizes['second'])}"
            )
    click.echo()


def _signal_arbiter(arbiter_pid: int) -> None:
    """Send SIGUSR1 to the arbiter, with a clean error if it's gone."""
    try:
        os.kill(arbiter_pid, signal.SIGUSR1)
    except (ProcessLookupError, PermissionError):
        click.secho(
            f"Server (pid {arbiter_pid}) is no longer running.",
            fg="red",
            err=True,
        )
        raise SystemExit(1)


def _find_arbiter_pid() -> int | None:
    """Find the PID of a running plain server arbiter."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "plain server"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return None
        # pgrep may return multiple PIDs — find ones that are parents
        # (have children), which are arbiters, not workers.
        my_pid = os.getpid()
        arbiters = []
        for line in result.stdout.strip().splitlines():
            pid = int(line.strip())
            if pid == my_pid:
                continue
            children = subprocess.run(
                ["pgrep", "-P", str(pid)],
                capture_output=True,
                text=True,
            )
            if children.returncode == 0 and children.stdout.strip():
                arbiters.append(pid)
        if len(arbiters) > 1:
            click.secho(
                f"Multiple servers found (PIDs: {', '.join(str(p) for p in arbiters)}).\n"
                f"Use --pid to specify which one.",
                fg="yellow",
                err=True,
            )
            return None
        return arbiters[0] if arbiters else None
    except (OSError, ValueError):
        return None


def _get_worker_pids(arbiter_pid: int) -> list[int]:
    """Find worker PIDs that are children of the arbiter."""
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(arbiter_pid)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.strip().splitlines():
            pid = int(line.strip())
            # Filter out resource_tracker processes
            try:
                cmdline = subprocess.run(
                    ["ps", "-o", "command=", "-p", str(pid)],
                    capture_output=True,
                    text=True,
                )
                if "resource_tracker" not in cmdline.stdout:
                    pids.append(pid)
            except OSError:
                pass
        return pids
    except (OSError, ValueError):
        return []
