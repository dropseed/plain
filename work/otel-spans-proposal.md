---
labels:
- plain.server
related:
- auth-otel-user-context
- metrics
---

# OTel Span Proposal: View + WebSocket

## Context

Removing `as_view()` also removed the INTERNAL span it created per view dispatch.
Before reconsidering where to add it back, we should think about spans holistically
across views, SSE, and websockets.

## What existed before

Two nested spans per HTTP request:

- **SERVER**: `GET /users/123/` (from `BaseHandler.get_response`)
- **INTERNAL**: `UserView` (from `as_view()` closure, now removed)

The INTERNAL span had `code.function` and `code.namespace` attributes
identifying the view class.

## Options for views

**A. Nested span in `_get_response` / `_get_response_async`**

- Restores what we had
- Gives view dispatch timing separate from middleware timing
- Extra span per request

**B. Add view class as attribute on existing SERVER span**

- Add `code.namespace` / `code.function` to the SERVER span
- `resolve_request` already updates the span with `http.route`
- Same info, no extra span overhead

**C. Drop it**

- SERVER span already has `http.route` (e.g. `/users/<int:id>/`)
- Route is 1:1 with the view class — the class name is redundant
- If you need middleware vs view timing, instrument middleware with their own spans

## WebSocket considerations

WebSocket connections are long-lived — a single SERVER span doesn't make sense
the same way it does for request/response. Things to think about:

- Should the upgrade/handshake be its own span?
- Should each message (receive/send) be a span?
- Should connect/disconnect be spans?
- How do other frameworks instrument WebSocket? (OpenTelemetry has no official semantic conventions for WebSocket yet)

## SSE considerations

SSE is long-lived like WebSocket but uses HTTP. The SERVER span currently covers
the entire streaming duration. Is that useful or does it create a misleadingly
long span?

## Decision

TBD — revisit after WebSocket support is integrated.
