# plain: response.defer()

- Run code after the HTTP response is sent to the client (like Laravel's `defer()`)
- Plain's server already calls `ResponseBase.close()` after the response body is written to the socket — insert deferred callbacks there
- Callbacks run after response is sent but before `request_finished` signal, so DB connections are still open
- Errors are logged but don't crash the server or block other callbacks
- Access log timing excludes deferred callback time (already the case architecturally)
- For long-running work, users should use `plain-jobs` instead

## API

```python
response = Response("Created!", status_code=201)
response.defer(send_welcome_email, user.email)
response.defer(track_event, "signup", user_id=user.id)
return response
```

## Implementation

Modify `ResponseBase` in `plain/plain/http/response.py`:

- Add `_deferred_callbacks` list to `__init__`
- Add `defer(func, *args, **kwargs)` method
- In `close()`, execute deferred callbacks after `_resource_closers` but before `request_finished`

## Prior art

- Laravel `defer()` — closure-based, runs after FastCGI response flush
- Starlette `BackgroundTasks` — tasks attached to response, run after ASGI send
- Rack `rack.after_reply` / `rack.response_finished` — server-level hook
