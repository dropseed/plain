def setup() -> None:
    # This package isn't an installed app,
    # so we need to trigger our own import and cli registration.
    from .cli import cli  # noqa
    from .backups import cli  # noqa
