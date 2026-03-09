---
packages:
- plain-admin
after: realtime-architecture
related:
- metrics
- pageviews-dashboard
---

# plain-admin: Live-Updating Charts via SSE

- Admin dashboard cards that update in realtime using Server-Sent Events
- Built on the existing `ServerSentEventsView` and `ChartCard`/`TrendCard` infrastructure
- Single SSE connection per page, multiplexed via the SSE `event:` field to target individual cards by slug

## Per-Page Stream Architecture

- Each admin view that declares live cards gets a companion stream URL (e.g. `/admin/dashboards/overview/stream/`)
- The stream view knows which cards to serve because it's tied to the parent view's `cards` list
- Avoids streaming data for cards the user isn't looking at
- One connection per page sidesteps the HTTP/1.1 six-connection-per-domain limit

## Server Side

- New `LiveCard` mixin or subclass with `get_live_data()` and `interval` attributes
- Admin view auto-registers a companion `ServerSentEventsView` for pages that have live cards
- Stream view loops over the page's live cards, calling `get_live_data()` for each, yielding `ServerSentEvent(data=..., event=card.get_slug())`
- ORM queries need `sync_to_async()` wrapping since the SSE view runs on the event loop
- Stream endpoint reuses admin auth (same session/permission checks)

## Client Side

- Page opens a single `EventSource` to its stream URL
- Each card registers `source.addEventListener(slug, ...)` for its own events
- Chart cards call `chart.data.labels.push()` / `chart.data.datasets[0].data.push()` / `chart.update('none')` for smooth appending
- Rolling window — shift old points off the left to keep a fixed number of data points
- Metric cards swap inner text on each event
- Live indicator (pulsing dot) shows the connection is active
- On HTMX card swap (filter change), close old EventSource listeners and re-register

## Multiplexed Event Format

```
event: card_app_users_signuptrend
data: {"label": "10:05", "value": 12}

event: card_app_orders_activecount
data: {"metric": 247}
```

## Use Cases

- Active sessions count (every 5s)
- Request rate line chart (every 1s)
- Job queue depth — pending/running/failed (every 3s)
- New signups bar chart appending (every 30s)
- Error rate rolling window (every 5s)
- Revenue today running total (every 10s)

## Open Questions

- How to handle cards with different update intervals — fastest interval with per-card modulo, or async tasks per card?
- Should `get_live_data()` return a full data point (append mode) or a complete replacement (snapshot mode), or support both?
- Connection lifecycle — reconnect strategy, keepalive comments to prevent proxy timeouts
