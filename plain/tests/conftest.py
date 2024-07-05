import os


def pytest_configure(config):
    os.environ["BOLT_ENV_SETTING"] = "1"
    os.environ["BOLT_ENV_OVERRIDDEN_SETTING"] = "env value"
    os.environ["BOLT_UNDEFINED_SETTING"] = "not used"
