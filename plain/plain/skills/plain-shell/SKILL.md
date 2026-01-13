---
name: plain-shell
description: Runs Python with Plain configured and database access. Use for scripts, one-off commands, or interactive sessions.
---

# Running Python with Plain

## Interactive Shell

```
uv run plain shell
```

## One-off Command

```
uv run plain shell -c "from app.users.models import User; print(User.query.count())"
```

## Run a Script

```
uv run plain run script.py
```
