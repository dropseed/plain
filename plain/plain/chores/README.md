# Chores

**Routine maintenance tasks.**

Chores are registered functions that can be run at any time to keep an app in a desirable state.

![](https://assets.plainframework.com/docs/plain-chores-run.png)

A good example is the clearing of expired sessions in [`plain.sessions`](/plain-sessions/plain/sessions/chores.py) — since the sessions are stored in the database, occasionally you will want to delete any sessions that are expired and no longer in use.

```python
# plain/sessions/chores.py
from plain.chores import register_chore
from plain.utils import timezone

from .models import Session


@register_chore("sessions")
def clear_expired():
    """
    Delete sessions that have expired.
    """
    result = Session.objects.filter(expires_at__lt=timezone.now()).delete()
    return f"{result[0]} expired sessions deleted"
```

## Running chores

The `plain chores run` command will execute all registered chores. When and how to run this is up to the user, but running them hourly is a safe assumption in most cases (assuming you have any chores — `plain chores list`).

There are several ways you can run chores depending on your needs:

- on deploy
- as a [`plain.worker` scheduled job](/plain-worker/plain/worker/README.md#scheduled-jobs)
- as a cron job (using any cron-like system where your app is hosted)
- manually as needed

## Writing chores

A chore is a function decorated with `@register_chore(chore_group_name)`. It can write a description as a docstring, and it can return a value that will be printed when the chore is run.

```python
# app/chores.py
from plain.chores import register_chore


@register_chore("app")
def chore_name():
    """
    A chore description can go here
    """
    # Do a thing!
    return "We did it!"
```

A good chore is:

- Fast
- Idempotent
- Recurring
- Stateless

If chores are written in `app/chores.py` or `{pkg}/chores.py`, then they will be imported automatically and registered.
