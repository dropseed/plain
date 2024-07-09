import pytest
from plain.runtime import settings, setup
from plain.test.client import Client, RequestFactory


def pytest_configure(config):
    # Run Plain setup before anything else
    setup()


@pytest.fixture(autouse=True, scope="session")
def _allowed_hosts_testserver():
    # Add testserver to ALLOWED_HOSTS so the test client can make requests
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]


@pytest.fixture()
def client() -> Client:
    """A Plain test client instance."""
    return Client()


@pytest.fixture()
def request_factory() -> RequestFactory:
    """A Plain RequestFactory instance."""
    return RequestFactory()
