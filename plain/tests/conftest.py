import os

import pytest

from plain.runtime import settings
from plain.test import Client
from plain.urls.resolvers import _get_cached_resolver


def pytest_configure(config):
    os.environ["PLAIN_ENV_SETTING"] = "1"
    os.environ["PLAIN_EXPLICIT_OVERRIDDEN_SETTING"] = "env value"
    os.environ["PLAIN_UNDEFINED_SETTING"] = "not used"
    os.environ["PLAIN_APP_REQUIRED_FROM_ENV"] = "from env"
    os.environ["PLAIN_APP_REQUIRED_TYPED_FROM_ENV"] = "42"

    from plain.packages.registry import packages_registry

    if not packages_registry.packages_ready:
        packages_registry.populate(settings.INSTALLED_PACKAGES)


@pytest.fixture
def error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = "error_routers.ErrorRouter"
    settings.DEBUG = False
    settings.URLS_TRAILING_SLASH = True
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
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


def _swap_router(
    router_path: str, *, debug: bool = False, urls_trailing_slash: bool = True
):
    """Yield a Client routed at `router_path`, restoring settings on teardown.

    `urls_trailing_slash` defaults to True so legacy fixtures whose
    routers spell slashed routes continue to behave as before. New
    fixtures that exercise the global default explicitly pass
    `urls_trailing_slash=False`.
    """
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    original_ts = settings.URLS_TRAILING_SLASH
    settings.URLS_ROUTER = router_path
    settings.DEBUG = debug
    settings.URLS_TRAILING_SLASH = urls_trailing_slash
    _get_cached_resolver.cache_clear()
    try:
        client = Client(raise_request_exception=False)
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        settings.DEBUG = original_debug
        settings.URLS_TRAILING_SLASH = original_ts
        _get_cached_resolver.cache_clear()


@pytest.fixture
def slash_client():
    """Client routed to `slash_routers.SlashRouter` for trailing-slash tests."""
    yield from _swap_router("slash_routers.SlashRouter")


@pytest.fixture
def boundary_client():
    """Client routed to `boundary_routers.BoundaryRouter` for include() boundary tests."""
    yield from _swap_router("boundary_routers.BoundaryRouter")


@pytest.fixture
def path_client():
    """Client routed to `path_routers.PathRouter` for raw-path edge case tests."""
    yield from _swap_router("path_routers.PathRouter")


@pytest.fixture
def catchall_client():
    """Client routed to `catchall_routers.CatchallRouter` for catchall semantics."""
    yield from _swap_router("catchall_routers.CatchallRouter")


@pytest.fixture
def included_catchall_client():
    """Catchall inside `include()` — pins that the catchall signal
    propagates through include wrapping."""
    yield from _swap_router("catchall_routers.IncludedCatchallRouter")
