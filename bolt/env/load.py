from os import environ

from dotenv import load_dotenv


def load(path: str = "", env_name: str = "") -> None:
    if path:
        return load_dotenv(path)

    if env_name:
        return load_dotenv(f".env.{env_name}")

    if app_env := environ.get("APP_ENV", ""):
        return load_dotenv(f".env.{app_env}")

    return load_dotenv()


__all__ = ["load"]
