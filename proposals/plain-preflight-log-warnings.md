# plain-preflight: Log warnings with `log.warning()`

- Preflight warnings should actually use `log.warning()` so they appear in logs
- Datadog queries can pick them up for monitoring/alerting
- Production visibility without manually running `plain preflight`

## Implementation

Add logging in `plain/plain/cli/preflight.py` where issues are displayed:

```python
import logging

logger = logging.getLogger("plain.preflight")

# In the display loop (around line 88-89):
if issue.warning:
    logger.warning(str(issue))
```

## Formatting

Keep it simple - `PreflightResult.__str__()` already provides clean formatting:

```
{obj}: ({id}) {fix}
```

Example output:

```
WARNING:plain.preflight: (preflight.allowed_hosts.wildcard) ALLOWED_HOSTS contains "*" which is no longer supported. Use [] for development or specify actual domains.
```

## Benefits

- Consistent with other Plain patterns (e.g., `HostValidationMiddleware` uses `logger.warning()`)
- Warnings visible in production logs and monitoring tools
- No changes to preflight check implementations - just add logging at display time
