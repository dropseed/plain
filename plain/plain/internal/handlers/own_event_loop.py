"""Running a coroutine to its end from code that isn't async.

Handling a request in-process is a plain function call, and part of a
request can be a coroutine: an async view, an async streaming body. Each is
run on an event loop made for it.
"""

import asyncio
import concurrent.futures
import contextvars
from collections.abc import Coroutine
from typing import Any


def run_on_own_event_loop[T](
    coroutine: Coroutine[Any, Any, T],
    *,
    context: contextvars.Context | None = None,
) -> T:
    """Run `coroutine` on an event loop of its own and return its result.

    `context` is the context its task runs in, as for
    `asyncio.Runner.run()`.

    The loop runs on this thread, unless this thread is already running
    one: the caller is itself a coroutine (an `async def` test making a
    request), and a thread runs one loop at a time. Then the new loop runs
    on another thread and this one waits for it. The caller's own loop
    makes no progress while it waits, as with any call that blocks.

    Either way `coroutine` runs in `context`. A `contextvars.Context`
    isn't tied to a thread, only entered by one at a time, and the caller
    is waiting, not running in it. What the caller put there (a test's
    database connection) is what the coroutine sees, and what the
    coroutine sets is there when it's done.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return _run(coroutine, context)

    def run_it() -> T:
        return _run(coroutine, context)

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="plain-in-process-loop"
    ) as one_thread:
        return one_thread.submit(run_it).result()


def _run[T](
    coroutine: Coroutine[Any, Any, T], context: contextvars.Context | None
) -> T:
    with asyncio.Runner() as runner:
        return runner.run(coroutine, context=context)
