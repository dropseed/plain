# Enforce 0001_initial migration naming

> **Note:** The [migration-rethink](migration-rethink/ARC.md) arc eliminates sequential numbering entirely in favor of timestamps. This future becomes unnecessary if that arc is implemented.

Guarantee that the first migration for every package is always named `0001_initial`. This simplifies the migration reset workflow by removing the conditional — if the name is guaranteed, reset is always just `migrations prune` (no `--fake` needed).

## Why

The reset process currently has a conditional: if the original first migration wasn't named `0001_initial`, you also need to `migrate --fake` the new one. Enforcing the name eliminates that branch entirely for both dev and production environments.

## Enforcement points

1. **Autodetector** — ignore `--name` for the first migration, always use `"initial"`. Needs a warning or error so users aren't confused when `--name` is silently ignored.
2. **Preflight check** — catch manual renames after the fact. Check that every package's graph root node is named `0001_initial`.

Both layers are needed: the autodetector prevents creation, the preflight catches renames.

## Once enforced

Simplify the "Resetting migrations" docs section in the postgres README to remove the conditional on the migration name.
