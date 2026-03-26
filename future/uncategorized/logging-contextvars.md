---
related:
  - jobs-structured-logging
---

# Request-scoped log context via contextvars

## Problem

`app_logger.context` is a mutable dict on a singleton logger instance — it's global state. If you set `app_logger.context["request_id"] = "abc"` in a middleware, it works in a single-threaded request flow, but it's shared across all concurrent requests. With async workers or free-threading, this is a race condition.

## How structlog solves this

structlog uses `contextvars.ContextVar` for cross-cutting context:

```python
# In middleware
structlog.contextvars.bind_contextvars(request_id="abc")

# In any logger, anywhere in the request
log.info("Order placed")  # automatically includes request_id
```

A processor (`merge_contextvars`) merges contextvar values into every log event. Because contextvars are scoped to the async task / thread, concurrent requests don't interfere.

## What this would look like in Plain

```python
from plain.logs import bind_context, clear_context

# In middleware (before_request)
bind_context(request_id=request_id, user_id=user.pk)

# In any code during the request
app_logger.info("Order placed", context={"order_id": "abc"})
# Output: [INFO] Order placed request_id=req-123 user_id=42 order_id=abc

# In middleware (after_response) or automatic cleanup
clear_context()
```

The formatter would merge contextvars + per-call context, same as structlog.

## Pros

- **Correct concurrency** — no shared mutable state across requests
- **Works for all loggers** — standard `logging.getLogger("plain.xxx")` loggers would get request context too, since the formatter reads contextvars, not just the logger instance
- **Middleware sets it once, everything benefits** — no need to pass context down the call stack
- **Free-threading ready** — contextvars are designed for this

## Cons

- **Implicit** — context appears in logs without being passed explicitly at the call site, which can be surprising
- **Cleanup burden** — must clear contextvars after each request or context leaks between requests (though middleware makes this straightforward)
- **Migration** — `app_logger.context["key"] = value` and `app_logger.include_context()` would need to change or become wrappers around contextvars
- **Debugging** — harder to inspect "what context is active right now" compared to looking at a dict on the logger

## Open questions

- Should `app_logger.context` become a contextvars-backed dict (transparent migration) or should it be a separate API (`bind_context`)?
- Should `include_context()` context manager use `contextvars.copy_context()` under the hood?
- Is this needed before free-threading lands, or is the current single-threaded request model safe enough for now?
