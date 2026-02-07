# plain-auth: Restore OpenTelemetry User Context

## Background

In v0.14.0, OpenTelemetry user ID attribute setting was added to `AuthenticationMiddleware`.
In v0.20.0, `AuthenticationMiddleware` was removed and replaced with `get_request_user()`.
The OTEL user attribute was lost in this transition.

This causes observability tools (Sentry, etc.) to not receive user context for traces and errors.

## Proposal

Restore OTEL user ID attribute in `get_request_user()`, with optional PII attributes.

### Changes to plain-auth/plain/auth/requests.py

```python
from opentelemetry import trace
from opentelemetry.semconv._incubating.attributes.user_attributes import USER_ID

def get_request_user(request: Request) -> User | None:
    if request not in _request_users:
        from .sessions import get_user

        user = get_user(request)

        if not user:
            return None

        # Set OTEL user attribute for observability
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attribute(USER_ID, str(user.id))

        _request_users[request] = user

    return _request_users[request]
```

## PII Consideration

OTEL semantic conventions also define:

- `user.email` (USER_EMAIL)
- `user.name` (USER_NAME)

### Option A: Only set user.id (recommended)

- `user.id` is not PII by itself
- Keep plain-auth simple, let downstream tools (Sentry, etc.) handle PII
- Matches original behavior before removal

### Option B: Add AUTH_OTEL_INCLUDE_PII setting

```python
# default_settings.py
AUTH_OTEL_INCLUDE_PII: bool = False
```

```python
# requests.py
span.set_attribute(USER_ID, str(user.id))

if settings.AUTH_OTEL_INCLUDE_PII:
    if email := getattr(user, "email", None):
        span.set_attribute(USER_EMAIL, email)
    if username := getattr(user, "username", None):
        span.set_attribute(USER_NAME, username)
```

This adds complexity and a new setting. PII handling is probably better left to Sentry-specific integrations (plainx-sentry) that already have `SENTRY_PII_ENABLED`.

## Recommendation

Go with Option A - only set `user.id`. This:

- Restores what was accidentally removed
- Keeps plain-auth simple
- Avoids new settings
- Lets observability tools handle PII based on their own settings
