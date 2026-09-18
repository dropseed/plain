import contextlib

import pytest
from plain.runtime import settings
from plain.test import Client
from plain.urls.resolvers import _get_cached_resolver


@contextlib.contextmanager
def swap_router(router_path: str):
    """Yield a Client routed to a different URLS_ROUTER for the duration of the block."""
    original = settings.URLS_ROUTER
    settings.URLS_ROUTER = router_path
    _get_cached_resolver.cache_clear()
    try:
        client = Client()
        # Middleware chain was built on init with the old router; rebuild it
        # after the settings swap.
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        _get_cached_resolver.cache_clear()


@pytest.fixture
def list_client():
    """Client routed to the list views in `list_routers.py`."""
    with swap_router("list_routers.ListRouter") as client:
        yield client
