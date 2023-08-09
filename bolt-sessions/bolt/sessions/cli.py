import click
from importlib import import_module

import django
from django.conf import settings


@click.group()
def cli():
    """Sessions management commands."""
    pass


@cli.command()
def clear():
    django.setup()
    engine = import_module(settings.SESSION_ENGINE)
    try:
        engine.SessionStore.clear_expired()
    except NotImplementedError:
        raise NotImplementedError(
            "Session engine '%s' doesn't support clearing expired "
            "sessions." % settings.SESSION_ENGINE
        )
