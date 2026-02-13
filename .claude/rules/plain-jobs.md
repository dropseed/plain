---
paths:
  - "**/jobs.py"
---

# Background Jobs

## Best Practices

### Offload slow work to jobs

Email, external API calls, and file processing should not block the HTTP response.

```python
# Bad — user waits for email to send
def post(self):
    send_welcome_email(user)
    return Response(...)

# Good — queue and respond immediately
def post(self):
    WelcomeUserJob(user).run_in_worker()
    return Response(...)
```

### Keep jobs idempotent

Jobs may retry on failure. Design them so re-execution is safe.

```python
# Bad — sends duplicate emails on retry
@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        send_welcome_email(self.user)

# Good — check before acting
@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        if not self.user.welcome_email_sent:
            send_welcome_email(self.user)
            self.user.welcome_email_sent = True
            self.user.save()
```

### Always use `@register_job`

Jobs must be decorated with `@register_job` so the worker can discover them.

```python
# Bad — worker can't find this job
class MyJob(Job):
    def run(self):
        ...

# Good
@register_job
class MyJob(Job):
    def run(self):
        ...
```

### Use `run_in_worker()` to enqueue jobs

Call `run_in_worker()` on a job instance to send it to the background queue.

```python
from plain.jobs import Job, register_job

@register_job
class ProcessDataJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        process(self.user)

# Enqueue with options
ProcessDataJob(user).run_in_worker(queue="slow", retries=3, priority=10)
```
