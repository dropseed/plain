---
packages:
  - plain-models
depends_on:
  - db-connection-pool-and-contextvars
related:
  - models-remove-db-connection-proxy
  - db-connection-pool
---

# Remove `validate_thread_sharing` from `DatabaseWrapper`

## Problem

`DatabaseWrapper` records `_thread_ident` at creation time and calls `validate_thread_sharing()` on every `cursor()`, `commit()`, `rollback()`, `close()`, and `savepoint()` call — raising `DatabaseError` if the current thread doesn't match.

This was Django's defense against passing connections between threads when using `threading.local()` storage. With ContextVar-based storage (after `db-connection-pool-and-contextvars`), cross-thread sharing through the normal access path is impossible by construction — each thread/task gets its own ContextVar context and its own wrapper.

The validation is now:

1. **Redundant** — the storage mechanism already guarantees isolation. Each thread's native ContextVar context holds its own `DatabaseWrapper`. There is no code path where one thread accesses another thread's connection through `db_connection`.

2. **Dead code with runtime cost** — 7 call sites check `_thread_ident` on every cursor, commit, rollback, close, and savepoint operation. The lock acquisition in `allow_thread_sharing` adds overhead to every check.

3. **Blocks future patterns** — if a reusable `copy_context()` pattern or `asyncio.to_thread()` is ever used to share a connection across threads (sequential access, not concurrent), `validate_thread_sharing` would raise even though the access is safe.

## What to remove

- `_thread_ident` attribute (line 222)
- `_thread_sharing_lock` attribute (line 220)
- `_thread_sharing_count` attribute (line 221)
- `allow_thread_sharing` property (line 818-821)
- `validate_thread_sharing()` method (line 823-835)
- All `self.validate_thread_sharing()` calls: `cursor()`, `commit()`, `rollback()`, `close()`, `savepoint()`, `savepoint_rollback()`, `savepoint_commit()` (7 call sites)
- `inc_thread_sharing()` and `dec_thread_sharing()` if they exist

## Risk

Low. The only scenario this catches is someone holding a direct reference to a `DatabaseWrapper` object and manually passing it to another thread — not going through `db_connection` / `get_connection()`. That's an obscure pattern that isn't used anywhere in the codebase, and ContextVar isolation makes it unreachable through the normal access path.
