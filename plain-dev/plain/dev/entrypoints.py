import os

from dotenv import load_dotenv


def load_dotenv_file():
    if plain_env := os.environ.get("PLAIN_ENV", ""):
        load_dotenv(f".env.{plain_env}")
    else:
        load_dotenv(".env")
