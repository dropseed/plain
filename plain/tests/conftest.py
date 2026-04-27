import os

import pytest

from plain.runtime import settings
from plain.test import Client
from plain.urls.resolvers import _get_cached_resolver


def pytest_configure(config):
    os.environ["PLAIN_ENV_SETTING"] = "1"
    os.environ["PLAIN_EXPLICIT_OVERRIDDEN_SETTING"] = "env value"
    os.environ["PLAIN_UNDEFINED_SETTING"] = "not used"

    from plain.packages.registry import packages_registry

    if not packages_registry.packages_ready:
        packages_registry.populate(settings.INSTALLED_PACKAGES)


@pytest.fixture
def error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    settings.URLS_ROUTER = "error_routers.ErrorRouter"
    settings.DEBUG = False
    _get_cached_resolver.cache_clear()
    try:
        client = Client(raise_request_exception=False)
        # Middleware chain was built on init with the old router; rebuild it
        # after the settings swap.
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        settings.DEBUG = original_debug
        _get_cached_resolver.cache_clear()
