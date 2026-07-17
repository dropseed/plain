from __future__ import annotations

import json
import sys
import time

import click

from plain.runtime import settings

from ..readiness import ReadinessResult, ReadinessStatus, check_database_ready

_WAIT_INTERVAL_SECONDS = 2.0


@click.command()
@click.option(
    "--wait",
    is_flag=True,
    help="Poll until the database is ready. Configuration errors still exit immediately.",
)
@click.option(
    "--timeout",
    type=float,
    help="With --wait, give up (exit 1) after this many seconds.",
)
@click.option("--json", "output_json", is_flag=True, help="Output as JSON")
def ready(wait: bool, timeout: float | None, output_json: bool) -> None:
    """Check that the database is ready for this application to serve.

    Verifies the database is reachable, all migrations are applied, and the
    schema has every model's table and columns. Runs against `POSTGRES_URL` —
    the connection the app serves through — so it belongs in serving
    entrypoints (before `plain server` / `plain jobs worker`), not release
    phases.

    Exit codes: 0 = ready, 1 = not ready but retryable (pending migrations,
    schema gap, database unreachable), 2 = configuration error a human must
    fix (bad credentials, database doesn't exist).
    """
    if timeout is not None and not wait:
        raise click.UsageError("--timeout requires --wait.")
    if output_json and wait:
        raise click.UsageError("--json cannot be combined with --wait.")

    if not wait:
        result = check_database_ready()
        exit_code = _exit_code(result)
        if output_json:
            # The exit code carries the CLI's policy (the DEBUG downgrade),
            # which the classification fields alone can't convey.
            payload = {"exit_code": exit_code, **result.to_dict()}
            click.echo(json.dumps(payload, indent=2))
        else:
            _print_result(result)
        sys.exit(exit_code)

    deadline = time.monotonic() + timeout if timeout is not None else None
    last_status: ReadinessStatus | None = None
    attempts = 0

    while True:
        # Deadline check before the next attempt (but always attempt at
        # least once) — an attempt can block for the full connect timeout,
        # which would overshoot --timeout by a lot.
        if attempts and deadline is not None and time.monotonic() >= deadline:
            click.secho(f"Timed out after {timeout:g}s.", fg="red", bold=True)
            sys.exit(1)

        result = check_database_ready()
        attempts += 1
        exit_code = _exit_code(result)

        if exit_code != 1:
            # Nothing to wait for: ready (or DEBUG warned past a gap), or a
            # configuration error a human must fix.
            _print_result(result)
            sys.exit(exit_code)

        if result.status is not last_status:
            # Full detail when the situation changes; one-liners between.
            _print_result(result)
            last_status = result.status
        else:
            click.secho(
                f"Not ready (attempt {attempts}): {result.summary()}",
                fg="yellow",
            )

        sleep_seconds = _WAIT_INTERVAL_SECONDS
        if deadline is not None:
            sleep_seconds = min(sleep_seconds, max(0.0, deadline - time.monotonic()))
        time.sleep(sleep_seconds)


def _exit_code(result: ReadinessResult) -> int:
    """Map the classification to the exit-code contract: 0 = serve,
    1 = retryable, 2 = a human must fix configuration.

    In DEBUG, schema gaps warn instead of gating — mid-development you
    routinely have a new model with no migration yet, and refusing to boot
    the dev server over a table you know about is hostile. Unreachable and
    config errors still fail in DEBUG; there's no serving through those.
    """
    match result.status:
        case ReadinessStatus.READY:
            return 0
        case ReadinessStatus.PENDING_MIGRATIONS | ReadinessStatus.SCHEMA_NOT_SATISFIED:
            return 0 if settings.DEBUG else 1
        case ReadinessStatus.CONFIG_ERROR:
            return 2
        case ReadinessStatus.UNREACHABLE:
            return 1
        case _:
            raise ValueError(f"Unhandled readiness status: {result.status}")


def _print_result(result: ReadinessResult) -> None:
    match result.status:
        case ReadinessStatus.READY:
            click.secho("✔ Database ready", fg="green")
            for name in result.pending_data_migrations:
                click.secho(
                    f"  ! {name} pending (data migration — not gating)", fg="yellow"
                )
        case ReadinessStatus.PENDING_MIGRATIONS:
            _print_not_ready_headline(result)
            for name in result.pending_migrations:
                click.echo(f"    {name}")
            for name in result.pending_data_migrations:
                click.secho(f"    {name} (data migration)", dim=True)
            click.secho(
                "  Run `plain migrations apply` (or `plain postgres sync`) to apply them.",
                dim=True,
            )
        case ReadinessStatus.SCHEMA_NOT_SATISFIED:
            _print_not_ready_headline(result)
            for table in result.missing_tables:
                click.echo(f"    table {table}")
            for column in result.missing_columns:
                click.echo(f"    column {column}")
            for name in result.pending_data_migrations:
                click.secho(f"    {name} (data migration pending)", dim=True)
            click.secho(
                "  No schema-affecting migrations are pending, so the database "
                "may be from a different version of this code — a restored "
                "backup, a rollback, or a database migrated by newer code.",
                dim=True,
            )
        case ReadinessStatus.UNREACHABLE:
            _print_connection_error(result, "Database unreachable")
            click.secho(
                "  This is usually temporary — the server may be starting, "
                "restarting, or briefly unreachable.",
                dim=True,
            )
        case ReadinessStatus.CONFIG_ERROR:
            _print_connection_error(result, "Database configuration error")
            click.secho(
                "  Retrying will not fix this — check POSTGRES_URL and the "
                "database server configuration.",
                dim=True,
            )


def _print_not_ready_headline(result: ReadinessResult) -> None:
    if settings.DEBUG:
        click.secho(
            f"! {result.summary()} — serving anyway in DEBUG, production would not",
            fg="yellow",
            bold=True,
        )
    else:
        click.secho(f"✗ Not ready: {result.summary()}", fg="red", bold=True)


def _print_connection_error(result: ReadinessResult, headline: str) -> None:
    """Print a possibly multi-line psycopg error with a one-line headline.

    psycopg reports multi-host failures as several lines ("Multiple
    connection attempts failed. All failures were: - host ..."); the first
    line goes on the headline (matching `summary()`) and the rest indent
    under it.
    """
    click.secho(f"✗ {headline}: {result.summary()}", fg="red", bold=True)
    for line in (result.connection_error or "").splitlines()[1:]:
        click.secho(f"    {line}", fg="red")
