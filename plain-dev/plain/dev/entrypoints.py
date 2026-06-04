from .dotenv import load_dotenv_files


def setup() -> None:
    # Make sure our clis are registered
    # since this isn't an installed app
    from .cli import cli  # noqa
    from .precommit import cli  # noqa
    from .contribute import cli  # noqa
    from .services import auto_start_services

    load_dotenv_files()

    # Auto-start dev services for commands that need the runtime
    auto_start_services()
