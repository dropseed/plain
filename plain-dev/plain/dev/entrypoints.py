import os
import subprocess
import sys

import click
from dotenv import load_dotenv

from .debug import set_breakpoint_hook
from .services import ServicesProcess


def setup():
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa

    # Try to set a new breakpoint() hook
    # so we can connect to pdb remotely.
    set_breakpoint_hook()

    # Load environment variables from .env file
    if plain_env := os.environ.get("PLAIN_ENV", ""):
        load_dotenv(f".env.{plain_env}")
    else:
        load_dotenv(".env")

    # If you run plain dev services --stop and it is already stopped, it can actually start one...
    auto_services = os.environ.get("PLAIN_DEV_SERVICES_AUTO", "true") in [
        "1",
        "true",
        "yes",
    ]
    if auto_services and not ServicesProcess.running_pid():
        result = subprocess.Popen(
            args=[sys.executable, "-m", "plain", "dev", "services"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        click.secho(
            f"Services started in the background (pid={result.pid})...", dim=True
        )
