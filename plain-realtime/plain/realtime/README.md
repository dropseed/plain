# Realtime

**Real-time server-to-client push using Postgres LISTEN/NOTIFY.**

- [Overview](#overview)
- [SSEView](#sseview)
- [Sending events](#sending-events)
- [Connecting from the browser](#connecting-from-the-browser)
- [Authorization](#authorization)
- [WebSocket views](#websocket-views)
- [Patterns](#patterns)
- [How it works](#how-it-works)

## Overview

The realtime module lets you push events to connected browsers. Define an `SSEView` with a URL, and the server handles SSE connections automatically. Events are sent from anywhere in your code using Postgres NOTIFY.

```python
# app/realtime.py
from plain.realtime import SSEView, notify


class UserNotifications(SSEView):
    def authorize(self):
        return self.request.user.is_authenticated

    def subscribe(self):
        return [f"user:{self.request.user.pk}"]
```

```python
# app/urls.py
from plain.urls import Router, path
from .realtime import UserNotifications


class AppRouter(Router):
    namespace = ""
    urls = [
        path("events/notifications/", UserNotifications),
    ]
```

```python
# In a view, job, signal handler — anywhere
from plain.realtime import notify

notify("user:42", {"type": "new_comment", "comment_id": 7})
```

```javascript
// In the browser
const events = new EventSource("/events/notifications/");
events.addEventListener("user:42", (e) => {
    const data = JSON.parse(e.data);
    // Update the UI
});
```

All `SSEView` methods are sync. You have full access to the ORM, sessions, and everything else via `self.request` — no `async def`, no `await`, no special wrappers.

For bidirectional WebSocket communication, see [WebSocket views](#websocket-views) below.

## SSEView

`SSEView` is a `View` subclass for Server-Sent Events. Register it in your URL router like any other view:

```python
# app/realtime.py
from plain.realtime import SSEView


class DashboardUpdates(SSEView):
    def authorize(self):
        return self.request.user.is_staff

    def subscribe(self):
        return ["dashboard:metrics"]

    def transform(self, channel_name, payload):
        # Optional: reshape the payload before sending to the client.
        # Return a dict (JSON-serialized), a string (sent as-is),
        # or None to skip this event.
        return {"metric": channel_name, "value": payload}
```

```python
# app/urls.py
from plain.urls import Router, path
from .realtime import DashboardUpdates


class AppRouter(Router):
    namespace = ""
    urls = [
        path("events/dashboard/", DashboardUpdates),
    ]
```

### SSEView methods

| Method                             | Purpose                                                  | Required                |
| ---------------------------------- | -------------------------------------------------------- | ----------------------- |
| `authorize()`                      | Return `True` to allow the connection, `False` for 403   | No (defaults to `True`) |
| `subscribe()`                      | Return a list of Postgres channel names to listen on     | Yes                     |
| `transform(channel_name, payload)` | Reshape the event before sending. Return `None` to skip. | No (sends raw payload)  |

All methods have access to `self.request` with `request.user`, the ORM, sessions, etc.

### Channel names

The strings returned by `subscribe()` are Postgres LISTEN/NOTIFY channel names. They can be any string, but a namespaced convention keeps things organized:

```python
def subscribe(self):
    return [
        f"user:{self.request.user.pk}",           # Per-user events
        f"org:{self.request.org.pk}",              # Per-organization events
        "system:announcements",                     # Global broadcast
    ]
```

A client receives events from all channels they're subscribed to. The `channel_name` argument in `transform()` tells you which one fired.

## Sending events

Call `notify()` from anywhere — views, jobs, signal handlers, management commands:

```python
from plain.realtime import notify

# Dict payload (JSON-serialized automatically)
notify("user:42", {"type": "new_message", "from": "alice"})

# String payload
notify("dashboard:metrics", "cpu:72.5")

# No payload (just a ping)
notify("user:42")
```

`notify()` calls Postgres `pg_notify()` under the hood. If called inside a transaction, the notification is only sent when the transaction commits. If the transaction rolls back, the notification is never sent.

Payloads are limited to ~8000 bytes. For larger data, send a reference and let the client fetch details:

```python
notify("user:42", {"type": "report_ready", "report_id": 99})
```

## Connecting from the browser

### SSE (recommended for most use cases)

```javascript
const events = new EventSource("/events/notifications/");

// Each event's type is the channel_name from subscribe().
// Use addEventListener to listen for specific channels.
events.addEventListener("user:42", (e) => {
    const data = JSON.parse(e.data);
    console.log("User event:", data);
});

events.onerror = () => {
    // EventSource auto-reconnects. This fires on each retry.
};
```

`EventSource` sends cookies automatically (same origin), so auth just works. The browser reconnects automatically if the connection drops.

### WebSocket

For bidirectional communication, use a `WebSocketView` (see [WebSocket views](#websocket-views)). For server-push only, `SSEView` is simpler and recommended.

## Authorization

`authorize()` runs in the sync request context with full access to cookies, sessions, and the ORM:

```python
class ProjectEvents(SSEView):
    def authorize(self):
        project_id = self.request.query_params.get("project_id")
        if not project_id:
            return False
        return ProjectMembership.query.filter(
            project_id=project_id,
            user=self.request.user,
        ).exists()

    def subscribe(self):
        project_id = self.request.query_params["project_id"]
        return [f"project:{project_id}"]
```

A failed `authorize()` returns a 403 response. An empty `subscribe()` list raises a `ValueError` — this is a programming error (you forgot to return channels), not an authorization failure.

## WebSocket views

For bidirectional communication with Postgres LISTEN/NOTIFY support, use `RealtimeWebSocketView`. It extends the base `WebSocketView` (from `plain.views`) with a `subscribe()` method for server-push events.

```python
from plain.realtime import RealtimeWebSocketView


class ChatSocket(RealtimeWebSocketView):
    async def authorize(self):
        return self.request.user.is_authenticated

    async def connect(self):
        room_id = self.url_kwargs["room_id"]
        await self.subscribe(f"chat:{room_id}")

    async def receive(self, message):
        # Called when the client sends a WebSocket message.
        await self.send(f"echo: {message}")

    async def disconnect(self):
        # Called when the connection closes. Optional.
        pass
```

```python
# urls.py
path("ws/chat/<room_id>/", ChatSocket)
```

### RealtimeWebSocketView methods

All methods from `WebSocketView` (see [views docs](../../../plain/plain/views/README.md#websocketview)), plus:

| Method               | Purpose                                                | Required |
| -------------------- | ------------------------------------------------------ | -------- |
| `subscribe(channel)` | Subscribe to a Postgres NOTIFY channel for push events | -        |

Call `subscribe()` in `connect()` to start receiving server-push events. Events from subscribed channels are automatically sent to the client as WebSocket messages.

**Note:** All methods are `async`. This is the one place in Plain where you write async code, because WebSocket lifecycle management requires it. You still have access to `self.request` for auth checking.

### SSE vs WebSocket: which to use

Most real-time use cases are **server-to-client push** (notifications, live updates, streaming AI). For these, use `SSEView`:

- Works over regular HTTP — no upgrade handshake
- Auth via cookies/headers, same as any request
- Browser's `EventSource` auto-reconnects
- Load balancers and proxies understand it natively

For cases where the client needs to send data (form input, chat messages), pair SSE with a normal HTTP POST. The server saves and calls `notify()`, and all SSE listeners receive the event.

Use `WebSocketView` when you genuinely need **high-frequency bidirectional messaging** — collaborative editing, multiplayer, or request/response patterns that would be too chatty over HTTP.

## Patterns

### Live notifications

```python
class Notifications(SSEView):
    def authorize(self):
        return self.request.user.is_authenticated

    def subscribe(self):
        return [f"user:{self.request.user.pk}"]
```

```python
# urls.py
path("events/notifications/", Notifications)
```

```python
# Anywhere in your app
def create_comment(request):
    comment = Comment.query.create(post=post, author=request.user, text=text)
    notify(f"user:{post.author_id}", {
        "type": "new_comment",
        "comment_id": comment.pk,
    })
    return redirect(post)
```

### Live dashboard

```python
class Dashboard(SSEView):
    def authorize(self):
        return self.request.user.is_staff

    def subscribe(self):
        return ["dashboard:metrics"]

    def transform(self, channel_name, payload):
        import json
        data = json.loads(payload)
        # Only send metrics this user cares about
        return data
```

```python
# In a background job
from plain.realtime import notify

def compute_metrics():
    metrics = calculate_current_metrics()
    notify("dashboard:metrics", metrics)
```

### Chat (SSE + POST pattern)

```python
class Chat(SSEView):
    def authorize(self):
        room_id = self.request.query_params.get("room")
        return ChatRoom.query.filter(
            pk=room_id, members=self.request.user
        ).exists()

    def subscribe(self):
        room_id = self.request.query_params["room"]
        return [f"chat:room:{room_id}"]
```

```python
# POST view for sending messages
def send_message(request):
    data = request.json_data
    room_id = data["room_id"]
    message = Message.query.create(
        room_id=room_id,
        author=request.user,
        text=data["text"],
    )
    notify(f"chat:room:{room_id}", {
        "type": "message",
        "id": message.pk,
        "author": request.user.username,
        "text": message.text,
    })
    return JsonResponse({"id": message.pk})
```

```javascript
// Browser: SSE for receiving, POST for sending
const events = new EventSource("/events/chat/?room=42");
events.addEventListener("chat:room:42", (e) => renderMessage(JSON.parse(e.data)));

function sendMessage(text) {
    fetch("/chat/send/", {
        method: "POST",
        body: JSON.stringify({ room_id: 42, text }),
    });
}
```

### AI agent streaming

```python
class AgentStream(SSEView):
    def authorize(self):
        session_id = self.request.query_params.get("session")
        return AgentSession.query.filter(
            pk=session_id, user=self.request.user
        ).exists()

    def subscribe(self):
        session_id = self.request.query_params["session"]
        return [f"agent:{session_id}"]
```

```python
# In a background job running the agent
def run_agent(session_id, prompt):
    for event in agent.run(prompt):
        notify(f"agent:{session_id}", {
            "type": event.type,
            "text": getattr(event, "text", ""),
        })
```

### WebSocket echo

```python
from plain.views import WebSocketView


class EchoSocket(WebSocketView):
    async def authorize(self):
        return True

    async def receive(self, message):
        await self.send(message)
```

## How it works

SSE and WebSocket connections use Postgres LISTEN/NOTIFY for event delivery and the server's built-in async infrastructure for connection management. No Redis, no external message broker, no separate process.

When a client connects to an SSE endpoint:

1. The server matches the URL to an `SSEView` via the URL router
2. `authorize()` and `subscribe()` run in the sync request context (full ORM access)
3. The connection is handed off to a background async thread in the worker process
4. The async thread subscribes to the specified Postgres channels via LISTEN
5. When a NOTIFY arrives, `transform()` runs (in a threadpool) and the result is sent to the client as an SSE event
6. Heartbeats detect dead connections; disconnected clients are cleaned up automatically

For WebSocket views, the server performs the HTTP upgrade handshake, then runs the view's async lifecycle methods (`connect`, `receive`, `disconnect`) on the event loop.

Each worker process maintains one Postgres connection for all LISTEN subscriptions, regardless of how many clients are connected. Events flow through Postgres to whichever worker holds the client's connection.

Your application code is always sync (except `WebSocketView`, which is async by nature). The async infrastructure is internal to the framework.
