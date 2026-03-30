# Deploy-Aware Rollouts

Potential future direction if Plain becomes aware of deployment lifecycle and app versions.

This is **not** part of the current migration rethink contract. The current answer is:

- ordinary deploy: `plain postgres sync`
- contraction deploy: `plain postgres sync --prune`

The motivation for a deploy-aware design is simple: manual contraction steps are acceptable as an escape hatch, but not ideal as the final UX. If Plain knows which release is rolling out and when old code is gone, it could automate more of the schema lifecycle safely.

## Why this is a separate problem

Convergence can reason about:

- desired schema
- actual schema
- online-safe DDL patterns

It cannot, by itself, reason about:

- whether old application instances are still serving traffic
- whether rollback is still likely/possible
- whether a destructive contraction is now safe

That is deployment state, not schema state.

## Possible shape

If Plain becomes deploy-aware, a single deploy action could be split internally into phases:

1. **Prepare**
    - additive, forward-only work
    - migrations
    - create indexes
    - add `NOT VALID` constraints
    - defaults and other rollout-compatible changes

2. **Enforce**
    - correctness-tightening work once the new release is fully live
    - `VALIDATE CONSTRAINT`
    - `SET NOT NULL`
    - any stricter contract the new code now depends on

3. **Prune**
    - contraction / cleanup after the rollback window
    - drop stale indexes and constraints
    - replace obsolete declarative objects

The deployer would still run one high-level operation, but Plain would schedule the internal phases using release awareness rather than requiring `--prune`.

## Requirements

Plain would need to know at least some of:

- current release identifier
- target release identifier
- which app instances are still on old code
- when the rollout is complete
- when the rollback window is closed

Without that information, the framework cannot safely infer when contraction should happen automatically.

## Why not now

- It expands Plain from schema management into deployment orchestration.
- It needs DB state plus app/runtime state.
- It adds operational concepts that are not required to fix the current migration/convergence model.

So the near-term design stays explicit:

- `sync` is the safe pre-deploy command
- `sync --prune` is the explicit contraction path

If the framework later grows deployment awareness, this doc is the obvious place to continue.
