---
paths:
  - "**/migrations/*.py"
---

# Package migrations

## FK to `users.User`

If your package has FK fields to `"users.User"`, `migrations create` (run in your package's test app) will pin the dependency to the test app's concrete migration — e.g., `("users", "0002_add_email")`. When shipped, that name won't exist in a consuming app's users package and the migration graph will fail to resolve.

Before committing, rewrite the dependency to the portable `__first__` form:

```python
# Change this:
dependencies = [
    ("users", "0002_add_email"),
]

# To this:
dependencies = [
    ("users", "__first__"),
]
```

`__first__` resolves at load time to whatever the consuming app's first users migration happens to be. The FK target itself (`to="users.User"`) is already stable — leave it alone.
