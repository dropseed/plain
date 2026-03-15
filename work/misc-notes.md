---
labels:
- plain
- plain-admin
- plain-models
- plain-flags
- plain-pageviews
- plain-support
- plain-pytest
- plain-start
- plain-tunnel
- plain-observer
- plain-toolbar
---

# Miscellaneous Notes

Random notes collected over time, investigated and categorized.

## Bugs / Fixes

### Admin: empty target_ids in perform_action

`plain-admin/plain/admin/views/objects.py` — when a user submits an action with no items selected, `target_ids` is `[]` and gets passed straight to `perform_action()` with no validation. The action silently runs against an empty queryset. Needs a guard + user-facing message.

### Admin: htmx boost 500 errors not shown

`admin.js` has `htmx:responseError` handling that shows an `alert()` with a generic message. For boosted links that 500, the HTML error body (which might have useful debug info) is never displayed. Could render the error response in a modal or inline panel instead.

### Tunnel: no guard against simultaneous instances

The tunnel client uses outbound WebSocket connections, so there's no port-binding collision to prevent duplicates. Running two tunnels for the same subdomain would cause undefined behavior — request metadata might go to one client while body chunks go to the other. Needs a PID lockfile or similar mechanism.

## Feature Ideas

### Observer: richer date display in sidebar

The observer traces sidebar shows relative time (`timesince`) with an absolute timestamp tooltip. Could bring in the richer datetime tooltips from admin (local time, UTC, relative, unix, ISO 8601, click-to-copy).

### Preflight: alert stale flags

Flags track `used_at` (updated every evaluation) and there's an existing `flags.unused_flags` preflight check. A complementary `flags.stale_flags` check could alert on flags that are in code but haven't been evaluated recently (old `used_at`), indicating dead code paths. Would need a configurable staleness threshold.

### Toolbar: debug mode indicator

The toolbar currently shows identically whether it appears because `DEBUG=True` or because the user is an admin in production. A "DEBUG" badge in the bottom bar (next to the version badge) would help developers immediately know they're in debug mode vs. production admin access.

### App starter: include .env.test

`plain-pytest` auto-loads `.env.test` if it exists, and the docs mention it. But the starter templates (`plain-start`) only include `.env` / `.env.example`. Adding a `.env.test` to the starter (with a test DB URL and test secret key) would help new users.

## Design Concerns

### Integrity errors with timestamp types

Possible type mismatch in unique constraint validation. In `constraints.py`, values are retrieved via `getattr(instance, field.attname)` as raw Python objects before `get_prep_value()` runs. If a timestamp comes in as a string instead of a `datetime` object, it could compare differently against existing rows or fail at the DB level. Also a timing issue with `auto_now_add` fields — `validate_unique()` might run before `pre_save()` sets the value.

### response.user in test client

`plain/test/client.py` — the test client soft-imports `plain.auth` and attaches the request's authenticated user onto the _response_ object. This leaks request context into the response, creates a hidden dependency on `plain.auth`, and is conceptually wrong (responses don't have users). Cleaner access would be `response.request.user`.

## Resolved

### db_connection proxy typing

Resolved: replaced `DatabaseConnection` proxy with `get_connection()` function that returns `DatabaseConnection` directly. All `cast()` workarounds removed.

### "raw" on admin detail

Was a "Toggle raw values" button showing unformatted `<code>{{ value }}</code>` alongside pretty-formatted values. Removed in v0.37.0 (commit `078f7da`) in favor of `format_field_value()`.

### UUID default on existing models

When adding a UUID field with `default=uuid.uuid4` to an existing table, `effective_default()` evaluates the callable once and uses that single UUID for all existing rows. A unique constraint then fails. This bit plain-flags, plain-pageviews, and plain-support — all three later had migrations removing those UUID fields.
