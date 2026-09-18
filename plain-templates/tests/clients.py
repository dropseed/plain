"""Clients routed at the test routers in this directory.

Each helper is a context manager: the router swap is scoped to the block, so
scope is visible as indentation rather than hidden in shared setup.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from plain.test import Client, override_settings
from plain.urls.resolvers import _get_cached_resolver


@contextmanager
def swap_router(
    router_path: str,
    *,
    debug: bool | None = None,
    raise_request_exception: bool = True,
) -> Generator[Client]:
    """Yield a Client routed to a different URLS_ROUTER for the duration of the block."""
    overrides: dict[str, object] = {"URLS_ROUTER": router_path}
    if debug is not None:
        overrides["DEBUG"] = debug

    try:
        with override_settings(**overrides):
            _get_cached_resolver.cache_clear()
            client = Client(raise_request_exception=raise_request_exception)
            # Middleware chain was built on init with the old router; rebuild it
            # after the settings swap.
            client.handler._middleware_chain = None
            client.handler.load_middleware()
            yield client
    finally:
        # Settings are restored by override_settings; clear the resolver
        # cache again so the original router is re-resolved.
        _get_cached_resolver.cache_clear()


@contextmanager
def error_client() -> Generator[Client]:
    """Client routed to the error-raising views in `error_routers.py`."""
    with swap_router(
        "error_routers.ErrorRouter", debug=False, raise_request_exception=False
    ) as client:
        yield client


@contextmanager
def list_client() -> Generator[Client]:
    """Client routed to the list views in `list_routers.py`."""
    with swap_router("list_routers.ListRouter") as client:
        yield client
