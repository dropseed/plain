# Remove squash command

## Why

The `migrations squash` command exists to consolidate migration history. With the migration rethink, every mechanism that made squash necessary is gone:

- **Fresh databases don't replay migrations** — they're created from model definitions
- **Migration files are simple** — just AddField/RemoveField/CreateModel, no index/constraint bloat
- **No dependency graph** — nothing complex to untangle when consolidating
- **Migration reset is trivial** — delete files, `migrations create`, `prune`

The `replaces` mechanism (Django's squash approach) added significant complexity to the migration loader and executor for a problem that no longer exists.

## What to do

Remove:

- `migrations squash` command
- `replaces` handling in migration loader
- `Migration.replaces` attribute
- Squash-related tests

The migration reset workflow (delete files, regenerate, prune) covers both app developers and package authors:

- **App developers**: reset when migration history is long
- **Package authors**: reset at major version boundaries, document "upgrade through vX first"

## Timing

This should be one of the last steps in the arc — only after fresh-db-from-models makes squash genuinely unnecessary.
