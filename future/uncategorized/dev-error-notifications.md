---
related:
  - dev-companion
---

# Dev Error Notifications

Surface server errors to the developer (and AI agents) without requiring them to actively watch the terminal.

## Problem

Errors stream through `plain dev` console logs, but if you're not watching the terminal you miss them. There's no push notification when something breaks, and no structured way to retrieve recent errors.

## Approach: Local Error Store + Desktop Notifications

Two capture layers feed into a single `~/.plain/dev/errors.jsonl` store:

1. **Logging handler** (inside server process) — catches request errors (500s, etc.) with full structured data from the log record
2. **Process manager** (in Poncho) — catches crash errors (syntax errors, import errors, bad config) by detecting unexpected process exits and capturing last stderr output

Both write to the same store. A desktop notification (macOS `osascript`) provides a nudge.

The error store is the primary value. The notification is secondary — just a "hey, go look" signal.

## Why two layers

The logging handler only works for errors during request handling — it lives inside the server process. If a syntax error or import error prevents the server from starting, the handler was never loaded. Those crashes only show up as subprocess stderr + a non-zero exit code.

The most annoying class of error to miss is exactly this: you save a file with a typo, the server tries to reload, crashes silently, and sits there dead until you notice your page isn't loading.

So the process manager catches what the log handler can't:

| Error type    | Example                           | Caught by       |
| ------------- | --------------------------------- | --------------- |
| Request error | `NameError` in a view → 500       | Log handler     |
| Import error  | `from app.models import Foo` typo | Process manager |
| Syntax error  | Missing colon, bad indent         | Process manager |
| Config error  | Bad setting crashes startup       | Process manager |

## Error store

Each error is a JSON line:

```json
{"timestamp": 1710000000.0, "source": "request", "exception": "NameError", "message": "name 'foo' is not defined", "path": "/dashboard/", "status_code": 500, "traceback": "..."}
{"timestamp": 1710000001.0, "source": "crash", "exception": null, "message": "SyntaxError: invalid syntax (models.py, line 42)", "path": null, "status_code": null, "traceback": "..."}
```

CLI to query it:

```
plain dev errors              # list recent errors
plain dev errors --last       # full traceback of most recent
plain dev errors --since 30s  # errors in last 30 seconds
plain dev errors --clear      # clear the store
```

The store resets on `plain dev` restart (or could be time-limited to last N errors).

## Implementation

### Log handler (request errors)

Handler (in `plain/logs/notify.py` or similar):

```python
class DevErrorHandler(logging.Handler):
    def __init__(self, error_log, cooldown=5):
        super().__init__()
        self.error_log = Path(error_log)
        self.cooldown = cooldown
        self.last_notify = 0

    def emit(self, record):
        entry = {
            "timestamp": record.created,
            "source": "request",
            "exception": (record.exc_info[1].__class__.__name__
                          if record.exc_info else None),
            "message": record.getMessage()[:500],
            "path": getattr(getattr(record, "request", None), "path", None),
            "status_code": getattr(record, "status_code", None),
            "traceback": self.format(record) if record.exc_info else None,
        }
        with self.error_log.open("a") as f:
            f.write(json.dumps(entry) + "\n")

        now = time.time()
        if now - self.last_notify < self.cooldown:
            return
        self.last_notify = now
        _desktop_notify(entry["message"][:200])
```

Wiring (in `configure_logging()`):

```python
if os.environ.get("PLAIN_DEV_ERROR_LOG"):
    handler = DevErrorHandler(error_log=os.environ["PLAIN_DEV_ERROR_LOG"])
    handler.setLevel(logging.ERROR)
    plain_logger.addHandler(handler)
```

### Process manager (crash errors)

In Poncho manager, when a process exits unexpectedly:

```python
if process.name == "server" and process.exit_code != 0:
    # Last stderr lines are already captured by Printer
    entry = {
        "timestamp": time.time(),
        "source": "crash",
        "exception": None,
        "message": last_stderr_lines[-1] if last_stderr_lines else "Server crashed",
        "path": None,
        "status_code": None,
        "traceback": "\n".join(last_stderr_lines),
    }
    # Write to same errors.jsonl + notify
```

### Env vars (in `plain-dev` server spawner)

```python
error_log = Path.home() / ".plain" / "dev" / "errors.jsonl"
env = os.environ.copy()
env["PLAIN_DEV_ERROR_LOG"] = str(error_log)
```

## Desktop notifications

```python
def _desktop_notify(msg):
    msg = msg.replace('"', '\\"')
    subprocess.Popen([
        "osascript", "-e",
        f'display notification "{msg}" with title "plain dev"'
    ])
```

macOS only via `osascript`. Could add Linux (`notify-send`) later. Time-based debounce (5s cooldown) prevents notification spam. Debounce state resets naturally on server reload.

## Claude Code integration

A `PostToolUse` hook on `Edit`/`Write` runs `plain dev errors --since 30s`. If there are errors, Claude sees them automatically and can fix without the developer needing to notice or intervene. The structured JSON output makes it easy for Claude to parse.

## Prior art

- **webpack-notifier / vite-plugin-notifier** — Desktop notifications on build errors (compile-time only, not runtime)
- **Next.js / Vite error overlay** — Shows errors in the browser as an overlay
- **Guard (Ruby)** — Watches files, runs checks, sends desktop notifications

The structured local error store with CLI query interface is novel. The AI agent integration angle (Claude automatically seeing errors after code changes) is new.
