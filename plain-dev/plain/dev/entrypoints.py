import os

from dotenv import load_dotenv

from .debug import set_breakpoint_hook


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .services import auto_start_services

    # Try to set a new breakpoint() hook
    # so we can connect to pdb remotely.
    set_breakpoint_hook()

    # Auto-start dev services for commands that need the runtime
    auto_start_services()

    # Load environment variables from .env file
    if plain_env := os.environ.get("PLAIN_ENV", ""):
        load_dotenv(f".env.{plain_env}")
    else:
        load_dotenv(".env")
