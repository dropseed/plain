import pytest
from plain.runtime import settings as plain_settings
from plain.runtime import setup

from .browser import TestBrowser


def pytest_configure(config):
    # Run Plain setup before anything else
    setup()


@pytest.fixture(autouse=True, scope="session")
def _allowed_hosts_testserver():
    # Add testserver to ALLOWED_HOSTS so the test client can make requests
    plain_settings.ALLOWED_HOSTS = [*plain_settings.ALLOWED_HOSTS, "testserver"]


@pytest.fixture
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


@pytest.fixture
def testbrowser(browser, request):
    """Use playwright and pytest-playwright to run browser tests against a test server."""
    try:
        # Check if isolated_db fixture is available from the plain-models package.
        # If it is, then we need to run a server that has a database connection to the isolated database for this test.
        request.getfixturevalue("isolated_db")

        from plain.models import DEFAULT_DB_ALIAS, connections

        def connection_to_url(
            connection,
        ) -> str:
            """Converts a database configuration to a URL string."""
            config = connection.settings_dict

            engine = config["ENGINE"].split(".")[-1]
            # Cheap for now...
            url = f"{engine}://{config['USER']}:{config['PASSWORD']}@{config['HOST']}:{config['PORT']}/{config['NAME']}"

            # Add options as query parameters.
            options = config["OPTIONS"]
            if options:
                query = "&".join(f"{k}={v}" for k, v in options.items())
                url += f"?{query}"

            return url

        # Get a database url for the isolated db that we can have gunicorn connect to also.
        database_url = connection_to_url(connections[DEFAULT_DB_ALIAS])
    except pytest.FixtureLookupError:
        # isolated_db fixture not available, use empty database_url
        database_url = ""

    testbrowser = TestBrowser(browser=browser, database_url=database_url)

    try:
        testbrowser.run_server()
        yield testbrowser
    finally:
        testbrowser.cleanup_server()
