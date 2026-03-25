---
paths:
  - "**/migrations/*.py"
---

# Package migrations

## SettingsReference fields

If your package has FK fields pointing to `SettingsReference("AUTH_USER_MODEL")`, `makemigrations` will hardcode the host app's concrete model in the generated migration (e.g., `to="users.user"` and a dependency on `("users", "0002_...")`).

You must manually fix these before committing:

1. Change `to="users.user"` to `to=settings.AUTH_USER_MODEL`
2. Change `("users", "...")` dependency to `migrations.settings_dependency(settings.AUTH_USER_MODEL)`
3. Add `from plain.runtime import settings` to the migration imports
