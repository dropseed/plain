import click

from plain.runtime import settings
from plain.utils.module_loading import import_string


@click.group()
def cli():
    """Sessions management commands."""
    pass


@cli.command()
def clear_expired():
    Session = import_string(settings.SESSION_CLASS)
    try:
        Session.clear_expired()
    except NotImplementedError:
        raise NotImplementedError(
            f"Session '{settings.SESSION_CLASS}' doesn't support clearing expired "
            "sessions."
        )
