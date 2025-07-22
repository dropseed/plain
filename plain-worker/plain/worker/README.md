# Worker

**Process background jobs with a database-driven worker.**

Jobs are defined using the `Job` base class and the `run()` method at a minimum.

```python
from plain.worker import Job, register_job
from plain.email import send_mail


@register_job
class WelcomeUserJob(Job):
    def __init__(self, user):
        self.user = user

    def run(self):
        send_mail(
            subject="Welcome!",
            message=f"Hello from Plain, {self.user}",
            from_email="welcome@plainframework.com",
            recipient_list=[self.user.email],
        )
```

You can then create an instance of the job and call `run_in_worker()` to enqueue it for a background worker to pick up.

```python
user = User.objects.get(id=1)
WelcomeUserJob(user).run_in_worker()
```

Workers are run using the `plain worker run` command.

## Installation

Install `plain.worker` and add it to your `INSTALLED_PACKAGES`.

```python
# app/settings.py
INSTALLED_PACKAGES = [
    ...
    "plain.worker",
]
```

Jobs can be defined in any Python file, but it is suggested to use `app/jobs.py` or `app/{pkg}/jobs.py` as those will be imported automatically so the `@register_job` will fire.

## Local development

In development, you will typically want to run the worker alongside your app. With [`plain.dev`](/plain-dev/plain/dev/README.md) you can do this by adding it to the `[tool.plain.dev.run]` section of your `pyproject.toml` file. Currently, you will need to use something like [watchfiles](https://pypi.org/project/watchfiles/) to add auto-reloading to the worker.

```toml
# pyproject.toml
[tool.plain.dev.run]
worker = {cmd = "watchfiles --filter python \"plain worker run --stats-every 0 --max-processes 2\" ."}
worker-slow = {cmd = "watchfiles --filter python \"plain worker run --queue slow --stats-every 0 --max-processes 2\" ."}
```

## Job parameters

TODO

## Admin

TODO

## Job history

TODO

## Scheduled jobs

TODO

## Monitoring

TODO
