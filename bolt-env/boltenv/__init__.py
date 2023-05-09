from os import environ

from dotenv import load_dotenv

from .cli import cli


def load(dotenv_path: str | None = None) -> None:
    if not dotenv_path:
        dotenv_path = environ.get("DOTENV", None)

    load_dotenv(dotenv_path)


__all__ = ["cli", "load"]
