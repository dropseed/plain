"""A response from the moment the view returns until it is closed.

The handler returns once the view is done, but the request isn't: a
streaming body is still app code (a sync generator can query the database,
an async one can await anything), and the response's resource closers —
returning the database connection, closing the request — run after the
last byte. `ResponseLifecycle` owns all of that.

`handle()` creates it holding the response, the request's
`contextvars.Context`, and the still-open SERVER span. The protocol writers
drive it with `send()`; the test client drives it with `read()`. Either way
the body runs in the request context, the closers run there once it's done,
and the span ends after the close — so the span's duration covers sending
the body, and a body that fails partway is recorded on it. A long-lived
stream (SSE) keeps its span open for as long as the client stays connected.

The writers own framing, flow control, and transport errors. This owns
everything that runs app code.
"""

import asyncio
import contextvars
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any, Self

from opentelemetry import metrics, trace
from opentelemetry.semconv._incubating.attributes.http_attributes import (
    HTTP_RESPONSE_BODY_SIZE,
)
from opentelemetry.semconv.attributes import (
    error_attributes,
    http_attributes,
    network_attributes,
    url_attributes,
)
from opentelemetry.semconv.metrics.http_metrics import HTTP_SERVER_REQUEST_DURATION
from plain.http import (
    AsyncStreamingResponse,
    FileResponse,
    Response,
    response_omits_body,
)
from plain.logs import get_framework_logger
from plain.utils.otel import format_exception_type

if TYPE_CHECKING:
    from plain.http import Request

log = get_framework_logger()
request_logger = get_framework_logger("plain.request")

# RFC 9110 standard methods + PATCH (RFC 5789).
# Unknown methods get normalized to _OTHER per OTel HTTP semconv.
KNOWN_HTTP_METHODS = frozenset(
    {"GET", "HEAD", "POST", "PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"}
)


def otel_http_method(method: str | None) -> str:
    """The request method as OTel HTTP semconv records it."""
    return method if method in KNOWN_HTTP_METHODS else "_OTHER"


meter = metrics.get_meter("plain")
request_duration_histogram = meter.create_histogram(
    name=HTTP_SERVER_REQUEST_DURATION,
    unit="s",
    description="Duration of HTTP server requests.",
)

# The end of a body, from a pull that ran out.
_END: Any = object()


class ResponseBodyError(Exception):
    """The response body raised partway through.

    It's already logged and recorded on the request span. The writer only
    has to end the response: a 500 if nothing went out yet, otherwise drop
    the connection.
    """


class ResponseLifecycle:
    """A response's body, its close, and the end of its request span.

    The server drives it by iterating it inside `send()`:

        async def write() -> None:
            async for chunk in lifecycle:
                ...

        await lifecycle.send(write)

    `send()` runs `write`, then closes the response, whether `write`
    finishes, raises, or is cancelled. `write` doesn't have to iterate — a
    HEAD response never reads its body. `close()` ends a response the
    writer never sends (a refused websocket upgrade).

    - A buffered `Response` yields its content, inline.
    - A sync `StreamingResponse` pulls one chunk per trip to the app thread
      pool, inside the request context. Batching several chunks per trip
      would hold each chunk back until the *next* `next()` returns, which
      changes when bytes reach the client for any stream that trickles.
      Consecutive chunks can land on different pool threads. A
      `FileResponse` reads its file on the loop's default executor instead
      — file reads are quick and shouldn't queue behind views.
    - An `AsyncStreamingResponse` runs, chunks and close, in one task bound
      to the request context (see `send()`).

    Every chunk reaches the writer, an empty one too — it still flushes
    the headers. A chunk that raises becomes a `ResponseBodyError`.

    **The status.** `sent_status_code` starts as the view's status. Whatever
    writes the response sets it, inside `write`, when it answers with
    something else — a 500 for a body that failed before its headers went
    out, a 503 for a refused upgrade — so the span and the duration metric
    record what went out.

    **Closing.** The response closes once, in the request context: its
    closers run (the generator's, returning the database connection,
    closing the request), then the span ends. A body with nothing left to
    run closes right away; a sync generator stopped partway closes on the
    pool, after any pull still running on a thread returns. A cancel can't
    drop that: the framework's closers and the span always finish. An async
    generator's own cleanup runs in its task and gets the usual asyncio
    guarantee — a second cancel can cut it short, but the closers after it
    still run.
    """

    def __init__(
        self,
        response: Response,
        *,
        request: Request,
        context: contextvars.Context,
        span: trace.Span,
        started: float,
        executor: Executor | None,
    ) -> None:
        self.response = response
        self.request = request
        self.context = context
        self.span = span
        self._started = started
        # Where a sync body's chunks are pulled and its close runs.
        self._executor: Executor | None
        if isinstance(response, FileResponse) and response.file_to_stream is not None:
            self._executor = None  # the loop's default executor
        else:
            self._executor = executor
        self._iterator: Any = None
        # The sync pull running on the pool, if any. Kept so the close can
        # tell a cancelled pull is still running on its thread.
        self._pull: asyncio.Future[Any] | None = None
        # What went out — see the class docstring. None when nothing did
        # (the client left, or a cancel, before the headers).
        self.sent_status_code: int | None = response.status_code
        self._body_read = False
        # The body ran to its end (or raised): nothing of it is left to run.
        self._body_done = False
        self._body_bytes = 0
        self._body_error: Exception | None = None
        self._close_started = False
        self._span_ended = False

    @property
    def headers_first(self) -> bool:
        """Whether the headers go out before the first chunk.

        An async stream is open-ended (SSE and the like): the client should
        see the response open even when the first event is a while coming.
        Everything else sends its headers with the first chunk, so a body
        that fails before producing one can still be answered with a 500.
        """
        return isinstance(self.response, AsyncStreamingResponse)

    # -- The server's driver --------------------------------------------

    async def send(self, write: Callable[[], Awaitable[None]]) -> None:
        """Run `write` (which iterates this body), then close the response.

        An async body runs in one task bound to the request context for the
        whole stream — every chunk and the close — so anything its generator
        holds across yields that belongs to a task (`asyncio.timeout`, a
        `TaskGroup`, an anyio cancel scope) stays with the task it was
        entered in. The task starts eagerly, so it's inside its `finally`
        before anything can cancel it, and awaiting it directly means
        cancelling `send()` cancels it and waits for its close.

        Everything else runs in the caller's task. A sync body can't share
        the async arrangement: its chunks run on pool threads inside the
        request context, and a task bound to that context couldn't resume
        while a pull still held it.
        """
        response = self.response
        if isinstance(response, AsyncStreamingResponse):
            await asyncio.get_running_loop().create_task(
                self._send_async(write, response),
                context=self.context,
                eager_start=True,
            )
            return

        try:
            await write()
        finally:
            await self._close_sync()

    async def close(self) -> None:
        """Close a response whose body is never sent (a refused websocket
        upgrade — set `sent_status_code` to what went out instead first)."""
        response = self.response
        if isinstance(response, AsyncStreamingResponse):
            await asyncio.get_running_loop().create_task(
                self._close_async(response), context=self.context, eager_start=True
            )
        else:
            await self._close_sync()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> bytes:
        chunk = await self._next_chunk()
        if chunk is _END:
            raise StopAsyncIteration
        self._body_bytes += len(chunk)
        return chunk

    async def _next_chunk(self) -> Any:
        if self._body_done:
            # Ended (or raised) already — no trip to find that out again.
            return _END
        response = self.response
        self._body_read = True

        if isinstance(response, AsyncStreamingResponse):
            # Already in the request context's task (see send()).
            if self._iterator is None:
                self._iterator = aiter(response)
            try:
                chunk = await anext(self._iterator, _END)
            except Exception as exc:
                self._body_done = True
                raise self._body_failed(exc, in_context=True) from exc
            self._body_done = chunk is _END
            return chunk

        if response.streaming:
            if self._iterator is None:
                self._iterator = iter(response)
            self._pull = asyncio.get_running_loop().run_in_executor(
                self._executor, self.context.run, next, self._iterator, _END
            )
            try:
                # Shielded: cancelling this await (a client reset, a
                # shutdown) can't stop the thread, so the pull future has to
                # stay awaitable for the close to know when it's done.
                chunk = await asyncio.shield(self._pull)
            except Exception as exc:
                self._body_done = True
                raise self._body_failed(exc, in_context=False) from exc
            self._body_done = chunk is _END
            return chunk

        if self._iterator is None:
            self._iterator = iter((response.content,))
        return next(self._iterator, _END)

    async def _send_async(
        self,
        write: Callable[[], Awaitable[None]],
        response: AsyncStreamingResponse,
    ) -> None:
        try:
            await write()
        finally:
            await self._close_async(response)

    async def _close_async(self, response: AsyncStreamingResponse) -> None:
        if self._close_started:
            return
        self._close_started = True
        try:
            # The response's own iterator wraps the view's; close both,
            # outer first, so neither is left suspended for the GC.
            if self._iterator is not None:
                await self._iterator.aclose()
            await response.aclose()
        except Exception:
            log.debug("Error closing async response body", exc_info=True)
        finally:
            # Runs even when the generator's cleanup is cancelled. This
            # task is already in the request context.
            response.close()
            self._end_span()

    async def _close_sync(self) -> None:
        if self._close_started:
            return
        self._close_started = True

        pull = self._pull
        if pull is not None and not pull.done():
            # Cancelled mid-pull: a pool thread is still inside the
            # generator. Closing it now raises ("generator already
            # executing"), and so does entering the context the thread is
            # in — close once the pull returns instead.
            pull.add_done_callback(self._close_after_pull)
            return

        if (
            self.response.streaming
            and self._iterator is not None
            and not self._body_done
        ):
            # Stopped partway (the client left): closing the generator runs
            # its `finally` blocks — app code that can block, same as its
            # chunks. Shielded so a cancel while the close waits for a free
            # thread can't drop it.
            closing = self._close_on_pool()
            if closing is not None:
                await asyncio.shield(closing)
            return

        # Nothing of the body is left to run — it's buffered, finished, or
        # never started — so the closers are framework bookkeeping (return
        # the database connection, close the request). Run them now rather
        # than wait for a free pool thread.
        self.context.run(self._finish)

    def _finish(self) -> None:
        """The close: the response's closers, then the span. Runs once, in
        the request context, however the response ended."""
        self.response.close()
        self._end_span()

    def _close_after_pull(self, pull: asyncio.Future[Any]) -> None:
        try:
            if not pull.cancelled():
                # Retrieve it so a failed pull nobody awaited isn't
                # reported as "exception was never retrieved".
                pull.exception()
            self._close_on_pool()
        except Exception:
            log.exception("Error closing a response after its pull")

    def _close_on_pool(self) -> asyncio.Future[Any] | None:
        """Close the response off the loop, in the request context, then
        end the span.

        Returns the pool's future, or None when the pool is already shut
        down (a hard stop) and the response was closed right here instead.
        """
        try:
            closing = asyncio.get_running_loop().run_in_executor(
                self._executor, self.context.run, self._finish
            )
        except RuntimeError:
            self.context.run(self._finish)
            return None
        closing.add_done_callback(self._closed_on_pool)
        return closing

    def _closed_on_pool(self, closing: asyncio.Future[Any]) -> None:
        if not closing.cancelled() and (exc := closing.exception()) is not None:
            log.error("Error closing a response", exc_info=exc)

    # -- The test client's driver ---------------------------------------

    def read(self) -> bytes:
        """Read the whole body on this thread, close, and return the body.

        The test client's driver: the same lifecycle as `send()` without a
        server. A sync body's chunks run here, in the request context; an
        async body runs on an event loop of its own. A body that raises
        partway is handled as the server handles it (logged, recorded on
        the span, set as `response.exception`), and the chunks before it
        are returned.
        """
        response = self.response
        consume = not response_omits_body(
            method=self.request.method, status_code=response.status_code
        )

        if isinstance(response, AsyncStreamingResponse):
            return asyncio.run(self._read_async(consume=consume))

        chunks: list[bytes] = []
        try:
            if consume and response.streaming:
                self._body_read = True
                iterator = iter(response)
                while True:
                    chunk: Any = self.context.run(next, iterator, _END)
                    if chunk is _END:
                        break
                    self._body_bytes += len(chunk)
                    chunks.append(chunk)
            elif consume:
                chunks.append(response.content)
        except Exception as exc:
            self._body_failed(exc, in_context=False)
            if not chunks:
                # What a server's writer sends: the headers go out with the
                # first chunk, so a body that fails before one gets a 500.
                self.sent_status_code = 500
        finally:
            self.context.run(self._finish)
        return b"".join(chunks)

    async def _read_async(self, *, consume: bool) -> bytes:
        chunks: list[bytes] = []

        async def write() -> None:
            if consume:
                async for chunk in self:
                    chunks.append(chunk)

        try:
            await self.send(write)
        except ResponseBodyError:
            pass
        return b"".join(chunks)

    # -- Shared ----------------------------------------------------------

    def _body_failed(self, exc: Exception, *, in_context: bool) -> ResponseBodyError:
        """Record a body that raised: logged in the request context (so
        the record carries the request's trace) and kept for the span. It
        becomes `response.exception` unless the view already set one — a
        5xx page whose body also failed keeps the view's error as the
        cause."""
        self._body_error = exc
        if self.response.exception is None:
            self.response.exception = exc
        if in_context:
            self._log_body_error(exc)
        else:
            self.context.run(self._log_body_error, exc)
        return ResponseBodyError(str(exc))

    def _log_body_error(self, exc: Exception) -> None:
        # Always an error with its traceback, whatever the exception: the
        # status is already decided by the time a body runs, so even an
        # HTTPException here (a 404 raised mid-export) is a server failure,
        # not the client error `log_exception` would treat it as.
        request_logger.error(
            "Response body failed", extra={"path": self.request.path}, exc_info=exc
        )

    def end_span(self) -> None:
        """End the request span and record the request's duration.

        Called once the response is closed. A websocket calls it at the
        handshake instead — the socket gets a span of its own.
        """
        self.context.run(self._end_span)

    def _end_span(self) -> None:
        """`end_span()`, for a caller already in the request context — so
        the duration measurement links to the request's trace."""
        if self._span_ended:
            return
        self._span_ended = True

        response = self.response
        span = self.span
        status_code = self.sent_status_code
        if status_code is not None:
            span.set_attribute(http_attributes.HTTP_RESPONSE_STATUS_CODE, status_code)
        if not response.streaming:
            span.set_attribute(HTTP_RESPONSE_BODY_SIZE, len(response.content))
        elif self._body_read:
            span.set_attribute(HTTP_RESPONSE_BODY_SIZE, self._body_bytes)

        # The metric's error.type is the status for a failed response, and
        # the exception type for a body that raised under a success status.
        metric_error_type: str | None = None
        if status_code is not None and status_code >= 500:
            metric_error_type = str(status_code)
        elif self._body_error is not None:
            metric_error_type = format_exception_type(self._body_error)

        if metric_error_type is not None:
            span.set_status(trace.StatusCode.ERROR)
            if response.exception is not None:
                span.record_exception(response.exception)
                span.set_attribute(
                    error_attributes.ERROR_TYPE,
                    format_exception_type(response.exception),
                )
            else:
                span.set_attribute(error_attributes.ERROR_TYPE, metric_error_type)
            if (
                self._body_error is not None
                and self._body_error is not response.exception
            ):
                # A 5xx page whose body also failed: the view's error is the
                # cause, and the body's is recorded alongside it.
                span.record_exception(self._body_error)

        # Recorded before the span ends, in the request context, so the
        # measurement's exemplar links to the request's trace.
        request = self.request
        duration_attrs: dict[str, str | int] = {
            http_attributes.HTTP_REQUEST_METHOD: otel_http_method(request.method),
            url_attributes.URL_SCHEME: request.scheme,
            network_attributes.NETWORK_PROTOCOL_NAME: "http",
        }
        if status_code is not None:
            duration_attrs[http_attributes.HTTP_RESPONSE_STATUS_CODE] = status_code
        if request.resolver_match and request.resolver_match.route is not None:
            duration_attrs[http_attributes.HTTP_ROUTE] = (
                f"/{request.resolver_match.route}"
            )
        if metric_error_type is not None:
            duration_attrs[error_attributes.ERROR_TYPE] = metric_error_type
        request_duration_histogram.record(
            time.perf_counter() - self._started, duration_attrs
        )
        span.end()
