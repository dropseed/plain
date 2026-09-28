"""`plain test` also runs where there is no app. There are no settings to
override there, and `override_settings` says so."""

from plain.packages import packages_registry
from plain.runtime import settings
from plain.test import AppRequiredError, override_settings, patch, raises


def test_override_settings_without_an_app_says_what_it_needs() -> None:
    with (
        patch(packages_registry, "ready", False),
        raises(AppRequiredError) as caught,
        override_settings(DEBUG=True),
    ):
        pass

    message = str(caught.exception)
    assert message.startswith("override_settings needs a Plain app")
    assert "run `plain test` from the directory that holds `app/`" in message


def test_override_settings_with_an_app_sets_and_restores() -> None:
    original = settings.DEBUG

    with override_settings(DEBUG=not original):
        assert settings.DEBUG is (not original)

    assert settings.DEBUG is original
