from __future__ import annotations

import asyncio
import base64
import os
import sys

import click

from plain.cli import register_cli

from .protocol import (
    DEFAULT_RELAY_HOST,
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    chunk_count,
    make_exec,
    make_file_pull,
    make_file_push,
)


def _check_response(response: dict) -> None:
    """Exit with an error message if the response indicates failure."""
    error = response.get("error")
    if error:
        print(error, file=sys.stderr)
        sys.exit(1)


@register_cli("portal")
@click.group()
def cli() -> None:
    """Remote Python shell and file transfer via encrypted tunnel."""


@cli.command()
@click.option("--code", default=None, help="Pre-set portal code (default: random).")
@click.option(
    "--writable", is_flag=True, help="Allow database writes (default: read-only)."
)
@click.option(
    "--timeout",
    default=30,
    type=int,
    help="Idle timeout in minutes (0 to disable).",
)
@click.option(
    "--relay-host",
    envvar="PLAIN_PORTAL_RELAY_HOST",
    default=DEFAULT_RELAY_HOST,
    hidden=True,
)
def start(code: str | None, writable: bool, timeout: int, relay_host: str) -> None:
    """Start a portal session on the remote machine."""
    if writable:
        if not click.confirm(
            "This session allows writes to the production database. Continue?"
        ):
            return

    from .remote import run_remote

    asyncio.run(
        run_remote(
            code=code, writable=writable, timeout_minutes=timeout, relay_host=relay_host
        )
    )


@cli.command()
@click.argument("code")
@click.option(
    "--foreground",
    is_flag=True,
    help="Run in foreground instead of backgrounding.",
)
@click.option(
    "--relay-host",
    envvar="PLAIN_PORTAL_RELAY_HOST",
    default=DEFAULT_RELAY_HOST,
    hidden=True,
)
def connect(code: str, foreground: bool, relay_host: str) -> None:
    """Connect to a remote portal session."""
    from .local import connect as do_connect

    asyncio.run(do_connect(code, relay_host=relay_host, foreground=foreground))


@cli.command("exec")
@click.argument("code")
@click.option("--json", "json_output", is_flag=True, help="Output as JSON.")
def exec_command(code: str, json_output: bool) -> None:
    """Execute Python code on the remote machine."""
    from .local import send_command

    request = make_exec(code, json_output=json_output)
    response = asyncio.run(send_command(request))
    _check_response(response)

    stdout = response.get("stdout", "")
    if stdout:
        print(stdout, end="")

    return_value = response.get("return_value")
    if return_value is not None:
        print(f"→ {return_value}")


@cli.command()
@click.argument("remote_path")
@click.argument("local_path")
def pull(remote_path: str, local_path: str) -> None:
    """Pull a file from the remote machine."""
    from .local import send_command

    request = make_file_pull(remote_path)
    response = asyncio.run(send_command(request))
    _check_response(response)

    if response.get("type") == "file_data":
        data = base64.b64decode(response["data"])
        with open(local_path, "wb") as f:
            f.write(data)
        print(f"Pulled {remote_path} → {local_path} ({len(data)} bytes)")
    else:
        print(f"Unexpected response: {response}", file=sys.stderr)
        sys.exit(1)


@cli.command()
@click.argument("local_path")
@click.argument("remote_path")
def push(local_path: str, remote_path: str) -> None:
    """Push a file to the remote machine."""
    from .local import send_command

    if not os.path.exists(local_path):
        print(f"File not found: {local_path}", file=sys.stderr)
        sys.exit(1)

    file_size = os.path.getsize(local_path)
    if file_size > MAX_FILE_SIZE:
        print(
            f"File too large: {file_size} bytes (max {MAX_FILE_SIZE})",
            file=sys.stderr,
        )
        sys.exit(1)

    async def _push_all() -> dict:
        chunks = chunk_count(file_size)
        response = {}
        with open(local_path, "rb") as f:
            for i in range(chunks):
                data = f.read(FILE_CHUNK_SIZE)
                request = make_file_push(
                    remote_path=remote_path, chunk=i, chunks=chunks, data=data
                )
                response = await send_command(request)
                if response.get("error"):
                    return response
        return response

    response = asyncio.run(_push_all())
    _check_response(response)

    total_bytes = response.get("bytes", file_size)
    print(f"Pushed {local_path} → {remote_path} ({total_bytes} bytes)")


@cli.command()
def disconnect() -> None:
    """Disconnect the active portal session."""
    from .local import disconnect as do_disconnect

    do_disconnect()


@cli.command()
def status() -> None:
    """Show portal session status."""
    from .local import status as do_status

    do_status()
