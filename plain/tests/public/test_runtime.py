from plain.runtime import settings


def test_user_settings():
    # Relies on env vars in conftest.py
    assert settings.DEFAULT_SETTING == "unchanged default"
    assert settings.EXPLICIT_SETTING == "explicitly changed"
    assert settings.ENV_SETTING == 1
    assert settings.EXPLICIT_OVERRIDDEN_SETTING == "env value"


def test_app_setting_annotation_only_loads_from_env():
    # Both are declared annotation-only in app/settings.py and supplied by
    # PLAIN_APP_* env vars in conftest.py. The int case proves the annotation
    # is wired into env parsing (not just stored).
    assert settings.APP_REQUIRED_FROM_ENV == "from env"
    assert settings.APP_REQUIRED_TYPED_FROM_ENV == 42
