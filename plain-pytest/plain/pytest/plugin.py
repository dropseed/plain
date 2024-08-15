import pytest
from plain.runtime import settings as plain_settings
from plain.runtime import setup
from plain.test.client import Client, RequestFactory


def pytest_configure(config):
    # Run Plain setup before anything else
    setup()


@pytest.fixture(autouse=True, scope="session")
def _allowed_hosts_testserver():
    # Add testserver to ALLOWED_HOSTS so the test client can make requests
    plain_settings.ALLOWED_HOSTS = [*plain_settings.ALLOWED_HOSTS, "testserver"]


@pytest.fixture()
def client() -> Client:
    """A Plain test client instance."""
    return Client()


@pytest.fixture()
def request_factory() -> RequestFactory:
    """A Plain RequestFactory instance."""
    return RequestFactory()


@pytest.fixture()
def settings():
    class SettingsProxy:
        def __init__(self):
            self._original = {}

        def __getattr__(self, name):
            return getattr(plain_settings, name)

        def __setattr__(self, name, value):
            if name.startswith("_"):
                super().__setattr__(name, value)
            else:
                if name not in self._original:
                    self._original[name] = getattr(plain_settings, name, None)
                setattr(plain_settings, name, value)

        def _restore(self):
            for key, value in self._original.items():
                setattr(plain_settings, key, value)

    proxy = SettingsProxy()
    yield proxy
    proxy._restore()
