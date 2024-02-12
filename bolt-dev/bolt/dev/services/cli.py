import click

from .core import Services


@click.group("services")
def cli():
    """Run databases and additional dev services in Docker Compose"""
    pass


@cli.command()
def up():
    """Start services"""
    click.secho("Starting services...", bold=True)
    started = Services().start()
    if not started:
        click.secho("No services to start", fg="yellow")
        return


@cli.command()
def down():
    Services().shutdown()
