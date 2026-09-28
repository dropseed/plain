from contextlib import contextmanager

from plain.test import Client, override_settings
from plain.urls.resolvers import _get_cached_resolver


@contextmanager
def _swap_router(router_path: str):
    """Yield a Client routed at `router_path`, restoring settings on exit.

    Trailing slashes are on, because these routers spell their routes with
    one. `test_urls_trailing_slash.py` has a helper of its own for the other
    setting.
    """
    try:
        with override_settings(
            URLS_ROUTER=router_path,
            DEBUG=False,
            URLS_TRAILING_SLASH=True,
        ):
            _get_cached_resolver.cache_clear()
            client = Client(raise_exceptions=False)
            yield client
    finally:
        # Settings are restored by override_settings; clear the resolver
        # cache again so the original router is re-resolved.
        _get_cached_resolver.cache_clear()


@contextmanager
def error_client():
    """Client routed to the error-raising views in `error_routers.py`."""
    with _swap_router("error_routers.ErrorRouter") as client:
        yield client


@contextmanager
def slash_client():
    """Client routed to `slash_routers.SlashRouter` for trailing-slash tests."""
    with _swap_router("slash_routers.SlashRouter") as client:
        yield client


@contextmanager
def boundary_client():
    """Client routed to `boundary_routers.BoundaryRouter` for include() boundary tests."""
    with _swap_router("boundary_routers.BoundaryRouter") as client:
        yield client


@contextmanager
def path_client():
    """Client routed to `path_routers.PathRouter` for raw-path edge case tests."""
    with _swap_router("path_routers.PathRouter") as client:
        yield client


@contextmanager
def catchall_client():
    """Client routed to `catchall_routers.CatchallRouter` for catchall semantics."""
    with _swap_router("catchall_routers.CatchallRouter") as client:
        yield client


@contextmanager
def included_catchall_client():
    """Catchall inside `include()` — pins that the catchall signal
    propagates through include wrapping."""
    with _swap_router("catchall_routers.IncludedCatchallRouter") as client:
        yield client
