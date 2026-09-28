"""Response bodies are app code, and run where the view ran.

The handler returns once the view is done, but a streaming body keeps
running app code — a sync generator can query the database. Before
`ResponseLifecycle`, the H1 writer iterated sync bodies directly on the event
loop (one slow `next()` stalled every connection on the worker) and both
protocols iterated outside the request's `contextvars.Context`, so a
generator's database queries used a different connection wrapper than the
view's — one the request's cleanup never returned, pinning a pool
connection for as long as the client kept its connection open.
"""

import asyncio
import contextvars
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import h2.events
import pytest
from plain.http import (
    AsyncStreamingResponse,
    FileResponse,
    Response,
    StreamingResponse,
)
from plain.internal.handlers.response_lifecycle import (
    ResponseBodyError,
    ResponseLifecycle,
)
from plain.test import RequestFactory
from server_stubs import (
    ContextHandler,
    capture_logger,
    h1_connect,
    h1_roundtrip,
    h2_connect,
    make_worker,
    stub_lifecycle,
)

_GET = b"GET / HTTP/1.1\r\nHost: testserver\r\n\r\n"

_request_value: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_request_value", default=None
)


def _handler(make_response: Callable[[], Response]) -> ContextHandler:
    """A handler whose view sets `_request_value` before building the response."""

    def view() -> Response:
        _request_value.set("from the view")
        return make_response()

    return ContextHandler(view)


def _where() -> bytes:
    on_loop = True
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        on_loop = False
    return f"value={_request_value.get()} on_loop={on_loop}".encode()


def _sync_where() -> StreamingResponse:
    def body() -> Iterator[bytes]:
        yield _where()

    return StreamingResponse(body(), content_type="text/plain")


def _async_where() -> AsyncStreamingResponse:
    async def body() -> AsyncIterator[bytes]:
        yield f"value={_request_value.get()}".encode()

    return AsyncStreamingResponse(body(), content_type="text/plain")


def test_h1_sync_stream_runs_off_the_loop_in_the_request_context() -> None:
    worker = make_worker(handler=_handler(_sync_where))
    _, body = asyncio.run(h1_roundtrip(worker, _GET))
    assert body == b"value=from the view on_loop=False"


def test_h2_sync_stream_runs_off_the_loop_in_the_request_context() -> None:
    async def scenario() -> None:
        client, server_task, executor = await h2_connect(
            _handler(_sync_where), asyncio.Event()
        )
        try:
            await client.request(1)
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )
            body = b"".join(
                e.data
                for e in client.events
                if isinstance(e, h2.events.DataReceived) and e.data
            )
            assert body == b"value=from the view on_loop=False"
        finally:
            client.writer.close()
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def test_h1_async_stream_runs_in_the_request_context() -> None:
    worker = make_worker(handler=_handler(_async_where))
    _, body = asyncio.run(h1_roundtrip(worker, _GET))
    assert body == b"value=from the view"


def test_h1_slow_sync_stream_leaves_the_loop_free() -> None:
    def slow_stream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            time.sleep(1)
            yield b"done"

        return StreamingResponse(body(), content_type="text/plain")

    async def scenario() -> None:
        client = await h1_connect(make_worker(handler=_handler(slow_stream)))
        try:
            await client.send(_GET)
            response = asyncio.create_task(client.read_response())

            # The longest the loop went without running this ticker while
            # the response was in flight. Iterated on the loop, one tick
            # waits out the whole sleep.
            longest_gap = 0.0
            last = time.monotonic()
            while not response.done():
                await asyncio.sleep(0.01)
                now = time.monotonic()
                longest_gap = max(longest_gap, now - last)
                last = now
            assert longest_gap < 0.5

            _, body = await response
            assert body == b"done"
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_h1_disconnect_mid_stream_closes_the_generator_in_context() -> None:
    closed_with: list[str | None] = []
    closed = threading.Event()

    def endless_stream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            try:
                while True:
                    yield b"x" * 65536
            finally:
                closed_with.append(_request_value.get())
                closed.set()

        return StreamingResponse(body(), content_type="text/plain")

    async def scenario() -> None:
        client = await h1_connect(make_worker(handler=_handler(endless_stream)))
        try:
            await client.send(_GET)
            await client.read_headers()
            client.writer.close()
            assert await asyncio.to_thread(closed.wait, 5)
            assert closed_with == ["from the view"]
        finally:
            client.teardown()

    asyncio.run(scenario())


def test_close_waits_for_a_cancelled_pull_to_finish() -> None:
    # A cancel (client reset, shutdown) can't stop a pull already running
    # on a pool thread. Closing the generator under it raises "generator
    # already executing" — the close has to wait for the pull to return.
    release = threading.Event()
    pulling = threading.Event()
    closed = threading.Event()

    def body() -> Iterator[bytes]:
        try:
            pulling.set()
            release.wait(5)
            yield b"late"
        finally:
            closed.set()

    async def scenario() -> None:
        lifecycle = _lifecycle(
            StreamingResponse(body(), content_type="text/plain"), executor
        )

        async def write() -> None:
            await anext(lifecycle)

        sending = asyncio.create_task(lifecycle.send(write))
        assert await asyncio.to_thread(pulling.wait, 5)
        sending.cancel()
        try:
            await sending
        except asyncio.CancelledError:
            pass
        assert not closed.is_set()

        release.set()
        assert await asyncio.to_thread(closed.wait, 5)

    executor = ThreadPoolExecutor(max_workers=1)
    try:
        asyncio.run(scenario())
    finally:
        release.set()
        executor.shutdown(wait=True)


def _pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1)


def _lifecycle(response: Response, executor: ThreadPoolExecutor) -> ResponseLifecycle:
    return stub_lifecycle(RequestFactory().get("/"), response, executor)


def test_failing_aclose_still_runs_the_resource_closers() -> None:
    closer_ran: list[bool] = []

    class FailingClose:
        def __aiter__(self) -> FailingClose:
            return self

        async def __anext__(self) -> bytes:
            raise StopAsyncIteration

        async def aclose(self) -> None:
            raise RuntimeError("aclose failed")

    async def scenario() -> None:
        response = AsyncStreamingResponse(FailingClose(), content_type="text/plain")
        response._resource_closers.append(lambda: closer_ran.append(True))
        lifecycle = _lifecycle(response, executor)

        async def write() -> None:
            assert [chunk async for chunk in lifecycle] == []

        await lifecycle.send(write)

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
    assert closer_ran == [True]


def test_cancelled_async_cleanup_still_runs_the_resource_closers() -> None:
    # The generator's cleanup awaits, and the send is cancelled while it
    # does (a shutdown cancel landing mid-teardown). CancelledError isn't
    # an Exception — the closers still have to run.
    closer_ran: list[bool] = []

    async def body() -> AsyncIterator[bytes]:
        try:
            yield b"first"
            await asyncio.sleep(10)
        finally:
            await asyncio.sleep(10)

    async def scenario() -> None:
        response = AsyncStreamingResponse(body(), content_type="text/plain")
        response._resource_closers.append(lambda: closer_ran.append(True))
        lifecycle = _lifecycle(response, executor)

        async def write() -> None:
            # One chunk, then stop — like a writer whose client left.
            await anext(lifecycle)

        sending = asyncio.create_task(lifecycle.send(write))
        await asyncio.sleep(0.05)  # now suspended in the generator's cleanup
        sending.cancel()
        try:
            await sending
        except asyncio.CancelledError:
            pass

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
    assert closer_ran == [True]


def test_async_generator_keeps_its_task_across_yields() -> None:
    # A timeout entered in the generator belongs to the task that entered
    # it. With a task per chunk, the timeout was bound to the first
    # chunk's (finished) task and never fired.
    async def body() -> AsyncIterator[bytes]:
        async with asyncio.timeout(0.2):
            while True:
                await asyncio.sleep(0.02)
                yield b"tick"

    async def scenario() -> None:
        response = AsyncStreamingResponse(body(), content_type="text/plain")
        lifecycle = _lifecycle(response, executor)

        async def write() -> None:
            async for _ in lifecycle:
                pass

        started = time.monotonic()
        with pytest.raises(ResponseBodyError) as raised:
            await asyncio.wait_for(lifecycle.send(write), timeout=2)
        # The generator's own timeout, well before wait_for's.
        assert isinstance(raised.value.__cause__, TimeoutError)
        assert time.monotonic() - started < 1

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)


def test_cancel_while_the_close_waits_for_a_thread_still_closes() -> None:
    # The client left partway, so closing the generator runs its `finally`
    # — app code, on the pool — and every pool thread is busy, so the close
    # queues. A cancel then (the worker is shutting down) must not drop it:
    # the closers return the database connection.
    busy = threading.Event()
    closed = threading.Event()

    def body() -> Iterator[bytes]:
        yield b"first"
        yield b"second"

    async def scenario() -> None:
        response = StreamingResponse(body(), content_type="text/plain")
        response._resource_closers.append(closed.set)
        lifecycle = _lifecycle(response, executor)
        occupied = asyncio.Event()

        async def write() -> None:
            await anext(lifecycle)  # one chunk, then the client left
            executor.submit(busy.wait, 5)  # occupy the only thread
            occupied.set()

        sending = asyncio.create_task(lifecycle.send(write))
        # Set in write(), so this resumes once send() has moved on to the
        # close and is waiting on it behind the busy thread.
        await occupied.wait()
        sending.cancel()
        try:
            await sending
        except asyncio.CancelledError:
            pass

        assert not closed.is_set()
        busy.set()
        assert await asyncio.to_thread(closed.wait, 5)

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        busy.set()
        executor.shutdown(wait=True)


def test_a_finished_stream_closes_without_waiting_for_a_thread() -> None:
    # Nothing of a drained body is left to run, so its closers (returning
    # the database connection) run right away — not behind busy views.
    busy = threading.Event()
    closed: list[bool] = []

    def body() -> Iterator[bytes]:
        yield b"only"

    async def scenario() -> None:
        response = StreamingResponse(body(), content_type="text/plain")
        response._resource_closers.append(lambda: closed.append(True))
        lifecycle = _lifecycle(response, executor)

        async def write() -> None:
            async for _ in lifecycle:
                pass
            executor.submit(busy.wait, 5)  # occupy the only thread

        await asyncio.wait_for(lifecycle.send(write), timeout=2)
        assert closed == [True]

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        busy.set()
        executor.shutdown(wait=True)


def test_h1_sync_stream_failing_before_its_first_chunk_is_a_500() -> None:
    # Headers go out with the first chunk, so a body that fails before
    # producing one can still be answered with a 500.
    def failing_stream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            raise ValueError("query failed")
            yield b"never"

        return StreamingResponse(body(), content_type="text/plain")

    worker = make_worker(handler=_handler(failing_stream))
    headers, _ = asyncio.run(h1_roundtrip(worker, _GET))
    assert headers.startswith(b"HTTP/1.1 500")


def test_h1_file_reads_dont_queue_behind_busy_app_threads() -> None:
    # File reads are quick; they run on the loop's default executor, not
    # the app pool that views are holding.
    release = threading.Event()

    def file_response() -> FileResponse:
        return FileResponse(BytesIO(b"file bytes"), content_type="text/plain")

    async def scenario() -> None:
        worker = make_worker(handler=_handler(file_response))
        worker.tpool.submit(release.wait, 5)  # the only app thread is busy
        try:
            _, body = await asyncio.wait_for(h1_roundtrip(worker, _GET), timeout=2)
            assert body == b"file bytes"
        finally:
            release.set()

    asyncio.run(scenario())


def test_cancel_before_the_async_task_starts_still_closes() -> None:
    # Cancelled right after send() creates the stream's task: a task that
    # never ran its first step never reaches its `finally`. It starts
    # eagerly, so it's already inside it.
    closer_ran: list[bool] = []

    async def events() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(10)
            yield b"never"

    async def scenario() -> None:
        response = AsyncStreamingResponse(events(), content_type="text/plain")
        response._resource_closers.append(lambda: closer_ran.append(True))
        lifecycle = _lifecycle(response, executor)

        async def write() -> None:
            async for _ in lifecycle:
                pass

        sending = asyncio.create_task(lifecycle.send(write))
        await asyncio.sleep(0)
        sending.cancel()
        try:
            await sending
        except asyncio.CancelledError:
            pass

    executor = _pool()
    try:
        asyncio.run(scenario())
    finally:
        executor.shutdown(wait=True)
    assert closer_ran == [True]


def test_h2_sync_stream_failing_before_its_first_chunk_is_a_500() -> None:
    # The same answer as H1: headers go out with the first chunk.
    def failing_stream() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            raise ValueError("query failed")
            yield b"never"

        return StreamingResponse(body(), content_type="text/plain")

    async def scenario() -> None:
        client, server_task, executor = await h2_connect(
            _handler(failing_stream), asyncio.Event()
        )
        try:
            await client.request(1)
            assert await client.response_status(1) == "500"
        finally:
            client.writer.close()
            server_task.cancel()
            executor.shutdown(wait=False)

    asyncio.run(scenario())


def _fails_before_first_chunk(*, log_access: bool = True) -> StreamingResponse:
    def body() -> Iterator[bytes]:
        raise ValueError("query failed")
        yield b"never"

    response = StreamingResponse(body(), content_type="text/plain")
    response.log_access = log_access
    return response


def test_h1_body_failing_before_headers_logs_one_500() -> None:
    # One request, one access line: the 500 that went out — not a 200 from
    # the writer followed by the error path's 500.
    worker = make_worker(handler=_handler(_fails_before_first_chunk))
    with capture_logger("plain.server.access") as access:
        headers, _ = asyncio.run(h1_roundtrip(worker, _GET))
    assert headers.startswith(b"HTTP/1.1 500")
    assert [r.__dict__.get("status") for r in access.records] == [500]


def test_h1_failed_body_respects_log_access() -> None:
    worker = make_worker(
        handler=_handler(lambda: _fails_before_first_chunk(log_access=False))
    )
    with capture_logger("plain.server.access") as access:
        headers, _ = asyncio.run(h1_roundtrip(worker, _GET))
    assert headers.startswith(b"HTTP/1.1 500")
    assert access.records == []


def test_h1_empty_first_chunk_flushes_the_headers() -> None:
    # A slow export can yield b"" to get its headers out before a router's
    # first-byte timeout; the headers go out with it.
    release = threading.Event()

    def slow_export() -> StreamingResponse:
        def body() -> Iterator[bytes]:
            yield b""
            release.wait(5)
            yield b"rows"

        return StreamingResponse(body(), content_type="text/csv")

    async def scenario() -> None:
        client = await h1_connect(make_worker(handler=_handler(slow_export)))
        try:
            await client.send(_GET)
            headers = await client.read_headers()
            assert headers.startswith(b"HTTP/1.1 200")
            release.set()
        finally:
            release.set()
            client.teardown()

    asyncio.run(scenario())


def test_body_error_keeps_the_views_exception() -> None:
    # A 5xx page whose body also fails: the view's error stays the cause.
    view_error = RuntimeError("view failed")

    def body() -> Iterator[bytes]:
        raise ValueError("page failed too")
        yield b"never"

    response = StreamingResponse(body(), status_code=500)
    response.exception = view_error

    executor = _pool()
    try:
        lifecycle = _lifecycle(response, executor)
        lifecycle.read()
    finally:
        executor.shutdown(wait=True)
    assert response.exception is view_error


class _KeepingHandler:
    """Hands back what it built, so a test can read what the writer
    recorded on it after the response went out."""

    def __init__(self, make_response: Callable[[], Response]) -> None:
        self.make_response = make_response
        self.sent: list[ResponseLifecycle] = []

    async def handle(self, request: object, executor: object) -> ResponseLifecycle:
        lifecycle = stub_lifecycle(request, self.make_response(), executor)
        self.sent.append(lifecycle)
        return lifecycle


def test_h1_records_the_status_it_answered_a_bad_header_with() -> None:
    # The app's own header fails to frame, before anything went out: the
    # writer answers it in place, and records that status — not the view's.
    def bad_header() -> Response:
        response = Response(b"ok", content_type="text/plain")
        response.headers["X Bad"] = "a header name can't have a space"
        return response

    handler = _KeepingHandler(bad_header)
    with capture_logger("plain.server.access") as access:
        headers, _ = asyncio.run(h1_roundtrip(make_worker(handler=handler), _GET))

    status = int(headers.split(b" ", 2)[1])
    assert status != 200
    [lifecycle] = handler.sent
    assert lifecycle.sent_status_code == status
    assert [r.__dict__.get("status") for r in access.records] == [status]


def test_body_http_exception_is_logged_as_a_server_error() -> None:
    # A 404 raised mid-export isn't a client error — the status was already
    # decided. It's logged as the failure it is.
    from plain.http import NotFoundError404

    def body() -> Iterator[bytes]:
        raise NotFoundError404("missing row")
        yield b"never"

    executor = _pool()
    try:
        with capture_logger("plain.request") as request_log:
            _lifecycle(StreamingResponse(body()), executor).read()
    finally:
        executor.shutdown(wait=True)
    [record] = request_log.records
    assert record.levelname == "ERROR"
    assert record.exc_info is not None


def test_h2_records_the_500_it_answered_an_early_failure_with() -> None:
    handler = _KeepingHandler(_fails_before_first_chunk)

    async def scenario() -> None:
        client, server_task, executor = await h2_connect(handler, asyncio.Event())
        try:
            await client.request(1)
            assert await client.response_status(1) == "500"
            await client.wait_for(
                lambda e: isinstance(e, h2.events.StreamEnded) and e.stream_id == 1
            )
        finally:
            client.writer.close()
            server_task.cancel()
            executor.shutdown(wait=False)

    with capture_logger("plain.server.access") as access:
        asyncio.run(scenario())
    [lifecycle] = handler.sent
    assert lifecycle.sent_status_code == 500
    assert [r.__dict__.get("status") for r in access.records] == [500]
