import os

from dotenv import load_dotenv

from .debug import set_breakpoint_hook


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
