from __future__ import annotations

import asyncio
import concurrent.futures

from middleware_helpers import (
    CtxVarRoundTripMiddleware,
    ctxvar_seen,
    request_ctxvar,
)

from plain.http import Response
from plain.internal.handlers.base import BaseHandler
from plain.runtime import settings
from plain.test import Client, RequestFactory
from plain.urls.resolvers import _get_cached_resolver


def test_handler():
    """
    Test that the handler processes a basic request and returns a response.
    """
    client = Client()
    response = client.get("/")

    assert response.status_code == 200
    assert response.content == b"Hello, world!"


def test_async_pipeline_shares_contextvars_across_threads():
    """
    For async views, `handle()` splits into two executor hops around the
    awaited coroutine. A `ContextVar` set by `before_request` on the
    first hop must still be visible to `after_response` on the second
    hop even when they land on different worker threads.

    Uses a 2-thread executor and asserts that `after_response` reads the
    sentinel value written by `before_request`.
    """
    ctxvar_seen.clear()
    original_router = settings.URLS_ROUTER
    original_middleware = list(settings.MIDDLEWARE)
    settings.URLS_ROUTER = "middleware_helpers.AsyncCtxVarRouter"
    settings.MIDDLEWARE = [
        "middleware_helpers.CtxVarRoundTripMiddleware",
        *original_middleware,
    ]
    _get_cached_resolver.cache_clear()
    try:
        handler = BaseHandler()
        handler.load_middleware()
        request = RequestFactory().get("/")

        async def run() -> Response:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                return await handler.handle(request, executor)

        response = asyncio.run(run())

        assert response.status_code == 200
        assert ctxvar_seen == ["set-by-before-request"]
        # Outside the request context, the ContextVar should be untouched —
        # each request runs in its own fresh `contextvars.Context()`, so
        # values set by middleware can't leak back to the server task.
        assert request_ctxvar.get() is None
    finally:
        settings.URLS_ROUTER = original_router
        settings.MIDDLEWARE = original_middleware
        _get_cached_resolver.cache_clear()

    # Use the imported class so the import isn't seen as unused.
    assert CtxVarRoundTripMiddleware.__name__ == "CtxVarRoundTripMiddleware"
