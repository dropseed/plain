---
related:
  - models-foreignkey-deferred-loading
  - models-consolidate-related-descriptors
---

# QuerySet Fetch Modes (N+1 Prevention)

## Problem

Lazy loading of ForeignKey relations and deferred fields causes N+1 queries — the most common ORM performance footgun. Today, developers must manually add `select_related()` or `prefetch_related()` to every query, or accept silent performance degradation.

## Proposed Solution: Fetch Modes

Three modes that control what happens when an unfetched field or relation is accessed:

| Mode            | Behavior                                             | N books + author |
| --------------- | ---------------------------------------------------- | ---------------- |
| **FETCH_ONE**   | Fetch for current instance only (status quo)         | 1 + N queries    |
| **FETCH_PEERS** | Batch-fetch for all instances from the same QuerySet | 2 queries        |
| **RAISE**       | Raise `FieldFetchBlocked` exception                  | Exception        |

### How FETCH_PEERS works

1. **Peer tracking at iteration time**: When `ModelIterable.__iter__` yields instances, it creates a shared `list` of `weakref.ref` objects. Each instance gets a reference to this same list via `_state.peers`.

2. **On lazy access**: When you hit e.g. `book.author` and it's not cached, the descriptor resolves all weak refs in the peers list, filters out GC'd ones, and calls `prefetch_related_objects(live_peers, "author")` — one `WHERE id IN (...)` query for all peers.

3. **Propagation**: The fetch mode cascades to related objects. Loading `book.author` with FETCH_PEERS means `book.author.publisher` also batch-fetches across all loaded authors.

4. **Graceful degradation**: If peers are garbage collected, falls back to single fetch. `.get()` (single object) has a 1-element peer list, also falls back. Pickling drops peers (weak refs aren't serializable).

## Open Question: What should the default be?

### Option A: FETCH_PEERS as default (auto-batch)

Plain is fast by default. No configuration needed. Most users never think about fetch modes.

- Pro: N+1 eliminated without developer effort
- Pro: Everything "just works" — no exceptions to handle during prototyping
- Con: First access to a relation triggers a batch query for ALL peers (could be large)
- Con: Hides data access patterns — harder to reason about query count

### Option B: RAISE as default (Ecto-style)

Forces explicit data loading. No surprise queries ever.

- Pro: Makes performance characteristics visible in code
- Pro: Pairs naturally with async (lazy loading can't be awaited)
- Pro: Ecto proves this works at scale
- Con: Significant friction for prototyping, shell exploration, admin
- Con: Every view needs prefetches tuned before it works at all
- Con: Rails found pain points: test fixtures, background jobs, admin all need escape hatches

### Option C: FETCH_PEERS default, RAISE encouraged for production views

Best of both worlds? Or confusing split personality?

## Prior Art

### Ecto (Phoenix/Elixir) — Raise is the only option

- No lazy loading at all. Unloaded associations return `Ecto.Association.NotLoaded` struct that errors on use.
- No opt-in/opt-out — this is the architecture.
- Community consensus: explicitness is worth the learning curve.

### Rails — Opt-in strict_loading (since 6.1)

- Default: lazy loading (FETCH_ONE equivalent).
- `strict_loading` raises `StrictLoadingViolationError` on lazy load.
- Two modes: `:all` (any lazy load) or `:n_plus_one_only` (only in loops).
- Can raise or log. Granularity: global, per-model, per-association, per-query.
- Not default due to backwards compat. Rails found real pain with fixtures, ActiveStorage, background jobs.
- Bullet gem (detection, not prevention) has been the community standard for years.

### Laravel — Opt-in preventLazyLoading (since 8.43)

- `Model::preventLazyLoading()` throws `LazyLoadingViolationException`.
- Commonly enabled only in dev: `Model::preventLazyLoading(!app()->isProduction())`.
- `handleLazyLoadingViolationUsing()` for custom behavior (log instead of throw).
- `Model::shouldBeStrict()` (9.35+) bundles lazy loading prevention with other strict checks.
- **Laravel 12.8 added `withRelationshipAutoloading()`** — their version of FETCH_PEERS, auto-batching lazy loads. Converging on the same two-pronged approach.

### Django — Fetch modes in 6.1 (under development)

- Three modes: `FETCH_ONE` (default), `FETCH_PEERS`, `RAISE`.
- Applied via `QuerySet.fetch_mode()`. Propagates to related objects.
- Default unchanged (FETCH_ONE) due to backwards compat.
- Inspired by `django-auto-prefetch` (FETCH_PEERS concept) and `django-seal` (RAISE concept), both by core contributors.
- `django-zen-queries` takes a different approach: block ALL queries in rendering phases.

### The trend

Every framework is moving away from silent lazy loading. The question is whether to auto-batch (FETCH_PEERS) or block (RAISE). Laravel is the most interesting data point — they added both, with auto-batch being the newest addition.

## API Design

Django's API is shaped by backwards compat (`QuerySet.fetch_mode(FETCH_PEERS)`). Plain can be more opinionated.

### Preferred direction: invisible default + explicit strict mode

```python
# Default behavior — FETCH_PEERS, no code needed, N+1 is just gone
books = Book.query.all()
for book in books:
    print(book.author.name)  # 2 queries, automatically

# Strict mode for performance-critical views
books = Book.query.strict()
for book in books:
    print(book.author.name)  # raises FieldFetchBlocked

# Opt out to single-fetch if needed (rare)
books = Book.query.lazy()
```

No `FETCH_ONE` / `FETCH_PEERS` / `RAISE` constants needed in the public API for the common case.

Could also support model-level override in Meta if needed.

## Implementation

### Touch points in Plain

| Piece                                    | Status                               | Location                         |
| ---------------------------------------- | ------------------------------------ | -------------------------------- |
| `ModelIterable.__iter__`                 | Add peer tracking                    | `query.py:110-131`               |
| `Model._state`                           | Add `.peers` and `.fetch_mode`       | `base.py:82-90`                  |
| `ForwardForeignKeyDescriptor.__get__`    | Intercept lazy load                  | `related_descriptors.py:156-168` |
| `Field.__get__` (deferred fields)        | Intercept for batch deferred loading | `fields/__init__.py:776-778`     |
| `prefetch_related_objects()`             | Reuse as batch engine                | `query.py:1835-1984`             |
| `get_prefetch_queryset()` on descriptors | Already builds batch queries         | `related_descriptors.py:89-129`  |

Estimated ~200-300 lines of new code. The existing `prefetch_related` machinery does the heavy lifting.
