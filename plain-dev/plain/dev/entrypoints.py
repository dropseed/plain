import os

from plain.utils.dotenv import load_dotenv


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .services import auto_start_services

    # Auto-start dev services for commands that need the runtime
    auto_start_services()

    # Load environment variables from .env file
    if plain_env := os.environ.get("PLAIN_ENV", ""):
        load_dotenv(f".env.{plain_env}")
    else:
        load_dotenv(".env")
