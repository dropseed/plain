---
labels:
  - plain-postgres
  - plain.views
---

# plain-postgres: Read-only transactions

## Done

Core read-only connection support shipped:

- `read_only()` context manager in `connections.py` — scoped read-only mode for a block of code
- `get_connection().set_read_only(True)` — sticky mode for shell sessions and scripts
- Uses PostgreSQL's `SET default_transaction_read_only` — works for both autocommit queries and explicit `atomic()` blocks
- `ReadOnlyError` exception (subclass of `InternalError`) for clear error reporting
- Raises `TransactionManagementError` if called inside an active transaction (the setting only affects the next transaction)

## Remaining

- View-level opt-in: `read_only = True` attribute on views, similar to existing view mixins
- GET/HEAD requests could default to read-only (opt-out with `read_only = False` on the view) — needs discussion on whether this should be automatic or explicit-only
- `plain shell --read-only` flag for a read-only shell session
