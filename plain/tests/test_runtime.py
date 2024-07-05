from plain.runtime import settings
from plain.runtime import (
    setup as plain_setup,  # Rename so pytest doesn't call setup()...
)


def test_setup():
    plain_setup()


def test_user_settings():
    plain_setup()

    # Relies on env vars in conftest.py
    assert settings.DEFAULT_SETTING == "unchanged default"
    assert settings.EXPLICIT_SETTING == "explicitly changed"
    assert settings.ENV_SETTING == 1
    assert settings.ENV_OVERRIDDEN_SETTING == "explicitly overridden"
