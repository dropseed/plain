# Chores

**Routine maintenance tasks.**

- [Overview](#overview)
- [Running chores](#running-chores)
- [Writing chores](#writing-chores)

## Overview

Chores are registered classes that can be run at any time to keep an app in a desirable state.

![](https://assets.plainframework.com/docs/plain-chores-run.png)

A good example is the clearing of expired sessions in [`plain.sessions`](/plain-sessions/plain/sessions/chores.py) — since the sessions are stored in the database, occasionally you will want to delete any sessions that are expired and no longer in use.

```python
# plain/sessions/chores.py
from plain.chores import Chore, register_chore
from plain.utils import timezone

from .models import Session


@register_chore
class ClearExpired(Chore):
    """Delete sessions that have expired."""

    def run(self):
        result = Session.query.filter(expires_at__lt=timezone.now()).delete()
        return f"{result[0]} expired sessions deleted"
```

## Running chores

The `plain chores run` command will execute all registered chores. When and how to run this is up to the user, but running them hourly is a safe assumption in most cases (assuming you have any chores — `plain chores list`).

There are several ways you can run chores depending on your needs:

- on deploy
- as a [`plain.jobs` scheduled job](/plain-jobs/plain/jobs/README.md#scheduled-jobs)
- as a cron job (using any cron-like system where your app is hosted)
- manually as needed

## Writing chores

A chore is a class that inherits from [`Chore`](./core.py#Chore) and implements the `run()` method. Register the chore using the [`@register_chore`](./registry.py#register_chore) decorator. The chore name is the class's qualified name (`__qualname__`), and the description comes from the class docstring.

```python
# app/chores.py
from plain.chores import Chore, register_chore


@register_chore
class ChoreName(Chore):
    """A chore description can go here."""

    def run(self):
        # Do a thing!
        return "We did it!"
```

### Best practices

A good chore is:

- **Fast** - Should complete quickly, not block for long periods
- **Idempotent** - Safe to run multiple times without side effects
- **Recurring** - Designed to run regularly, not just once
- **Stateless** - Doesn't rely on external state between runs

If chores are written in `app/chores.py` or `{pkg}/chores.py`, then they will be imported automatically and registered.
