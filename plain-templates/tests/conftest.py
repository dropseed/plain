import contextlib

import pytest

from plain.runtime import settings
from plain.test import Client
from plain.urls.resolvers import _get_cached_resolver


@contextlib.contextmanager
def swap_router(
    router_path: str,
    *,
    debug: bool | None = None,
    raise_request_exception: bool = True,
):
    """Yield a Client routed to a different URLS_ROUTER for the duration of the block."""
    original = settings.URLS_ROUTER
    original_debug = settings.DEBUG
    settings.URLS_ROUTER = router_path
    if debug is not None:
        settings.DEBUG = debug
    _get_cached_resolver.cache_clear()
    try:
        client = Client(raise_request_exception=raise_request_exception)
        # Middleware chain was built on init with the old router; rebuild it
        # after the settings swap.
        client.handler._middleware_chain = None
        client.handler.load_middleware()
        yield client
    finally:
        settings.URLS_ROUTER = original
        settings.DEBUG = original_debug
        _get_cached_resolver.cache_clear()


@pytest.fixture
def error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    with swap_router(
        "error_routers.ErrorRouter", debug=False, raise_request_exception=False
    ) as client:
        yield client


@pytest.fixture
def list_client():
    """Client routed to the list views in `list_routers.py`."""
    with swap_router("list_routers.ListRouter") as client:
        yield client
