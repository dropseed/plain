from bolt.runtime import settings
from bolt.runtime import setup as bolt_setup  # Rename so pytest doesn't call setup()...


def test_setup():
    bolt_setup()


def test_user_settings():
    bolt_setup()

    # Relies on env vars in conftest.py
    assert settings.DEFAULT_SETTING == "unchanged default"
    assert settings.EXPLICIT_SETTING == "explicitly changed"
    assert settings.ENV_SETTING == 1
    assert settings.ENV_OVERRIDDEN_SETTING == "explicitly overridden"
