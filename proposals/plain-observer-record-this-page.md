# plain-observer: Record This Page

- Add a `PERSIST_ONCE` observer mode — persists one trace then auto-reverts to summary
- "Record This Page" button in the observer panel sets the cookie via POST, then reloads the parent page (`window.top.location.reload()`)
- Toolbar button template (`observer_button.html`) detects `persist_once` on the next page load and auto-POSTs to reset to `summary` (same pattern as the auto-enable in `observer.html`)
- Works in production — cookie-based, no DEBUG-only header needed

## Files

- `core.py` — add `PERSIST_ONCE` to `ObserverMode`, update `is_enabled()`/`is_persisting()`, add `is_persist_once()` and `enable_persist_once_mode()`
- `otel.py` — update all mode checks (sampler, span processor, recording mode) to treat `PERSIST_ONCE` same as `PERSIST`
- `views.py` — extend `post()` to handle `observe_action=persist_once`
- `observer_button.html` — add auto-reset script and "Recording once..." label for `persist_once`
- `traces.html` — add "Record This Page" button in sidebar header, summary empty state, and disabled empty state
