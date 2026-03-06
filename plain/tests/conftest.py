import os


def pytest_configure(config):
    os.environ["PLAIN_ENV_SETTING"] = "1"
    os.environ["PLAIN_EXPLICIT_OVERRIDDEN_SETTING"] = "env value"
    os.environ["PLAIN_UNDEFINED_SETTING"] = "not used"

    from plain.packages.registry import packages_registry
    from plain.runtime import settings

    if not packages_registry.packages_ready:
        packages_registry.populate(settings.INSTALLED_PACKAGES)
