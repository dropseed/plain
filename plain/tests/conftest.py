import os


def pytest_configure(config):
    os.environ["PLAIN_ENV_SETTING"] = "1"
    os.environ["PLAIN_ENV_OVERRIDDEN_SETTING"] = "env value"
    os.environ["PLAIN_UNDEFINED_SETTING"] = "not used"
