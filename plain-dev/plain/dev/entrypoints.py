from dotenv import load_dotenv


def load_dotenv_file():
    loaded = load_dotenv(".env")
    if not loaded:
        # In CI-like environments, we may have .env.test committed
        # but not .env, so we can help out by loading it here.
        load_dotenv(".env.test")
