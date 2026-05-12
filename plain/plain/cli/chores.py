import sys

import click
from opentelemetry import trace
from opentelemetry.semconv.attributes.error_attributes import ERROR_TYPE

from plain.logs import get_framework_logger
from plain.utils.otel import format_exception_type

logger = get_framework_logger()
tracer = trace.get_tracer("plain")


@click.group()
def chores() -> None:
    """Routine maintenance tasks"""
    pass


@chores.command("list")
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
def list_chores(name: tuple[str, ...]) -> None:
    """List all registered chores"""
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    chore_classes = chores_registry.get_chores()

    if name:
        chore_classes = [
            chore_class
            for chore_class in chore_classes
            if f"{chore_class.__module__}.{chore_class.__qualname__}" in name
        ]

    for chore_class in chore_classes:
        chore_name = f"{chore_class.__module__}.{chore_class.__qualname__}"
        click.secho(f"{chore_name}", bold=True, nl=False)
        description = chore_class.__doc__.strip() if chore_class.__doc__ else ""
        if description:
            click.secho(f": {description}", dim=True)
        else:
            click.echo("")


@chores.command("run")
@click.option(
    "--name", default=None, type=str, help="Name of the chore to run", multiple=True
)
@click.option(
    "--dry-run", is_flag=True, help="Show what would be done without executing"
)
def run_chores(name: tuple[str, ...], dry_run: bool) -> None:
    """Run specified chores"""
    from plain.chores.registry import chores_registry

    chores_registry.import_modules()

    chore_classes = chores_registry.get_chores()

    if name:
        chore_classes = [
            chore_class
            for chore_class in chore_classes
            if f"{chore_class.__module__}.{chore_class.__qualname__}" in name
        ]

    chores_failed = []

    for chore_class in chore_classes:
        chore_name = f"{chore_class.__module__}.{chore_class.__qualname__}"
        click.echo(f"{chore_name}:", nl=False)
        if dry_run:
            click.secho(" (dry run)", fg="yellow", nl=False)
            continue

        with tracer.start_as_current_span(
            f"chore {chore_name}", kind=trace.SpanKind.INTERNAL
        ) as span:
            try:
                chore = chore_class()
                result = chore.run()
            except Exception as e:
                # The catch is inside the span, so the SDK's auto-record
                # on context exit won't fire — stamp the canonical
                # failure signal explicitly.
                span.record_exception(e)
                span.set_status(trace.StatusCode.ERROR)
                span.set_attribute(ERROR_TYPE, format_exception_type(e))
                click.secho(" Failed", fg="red")
                chores_failed.append(chore_class)
                logger.exception(
                    "Error running chore", extra={"chore_name": chore_name}
                )
                continue

        if result is None:
            click.secho(" Done", fg="green")
        else:
            click.secho(f" {result}", fg="green")

    if chores_failed:
        sys.exit(1)
