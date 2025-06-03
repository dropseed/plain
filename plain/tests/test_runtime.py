from plain.runtime import settings


def test_user_settings():
    # Relies on env vars in conftest.py
    assert settings.DEFAULT_SETTING == "unchanged default"
    assert settings.EXPLICIT_SETTING == "explicitly changed"
    assert settings.ENV_SETTING == 1
    assert settings.ENV_OVERRIDDEN_SETTING == "explicitly overridden"
