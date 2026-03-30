# Generated baseline artifact

## Why this might exist

The current fresh-db direction is: read the models, generate the schema at runtime, then converge. That is simple and keeps the models as the source of truth.

For self-hosted installs, there is a useful follow-on variation: generate a **baseline artifact** from those same models at release time, check it in, and use that artifact for fresh installs.

This is not a different source of truth. The baseline still comes **from models**. The difference is that the generated SQL becomes a reviewed release artifact instead of being re-derived dynamically on every fresh install.

## What it would do

At release time:

1. Build a canonical schema from current models and convergence-managed declarations
2. Emit a checked-in SQL artifact such as `postgres/baseline.sql`
3. Optionally record metadata like the release version or baseline id

On a fresh install:

1. Load the baseline artifact
2. Run convergence to verify/fix any remaining declarative state
3. Mark pre-baseline schema migrations as satisfied

On an existing install:

- Keep using normal incremental migrations plus convergence
- Do **not** apply the baseline artifact during a normal upgrade

So the baseline is mainly a fresh-install path, not a second upgrade mechanism.

## Why this could be useful

- **Stable install semantics per release.** Changes to the schema generator don't silently change how an older release bootstraps a database.
- **Reviewable DDL.** The exact SQL for a release is visible in code review.
- **Support-window boundary.** If Plain later defines a minimum supported upgrade version, the baseline can mark the oldest version from which upgrades are guaranteed.
- **Room for future DB-native objects.** If Plain later wants to include views, triggers, functions, or extensions in first-class setup, a baseline artifact is a natural place to capture them.

## Why this is a follow-on, not the starting point

The current model-driven fresh-db path is still the simplest core design:

- no extra artifact to generate
- no extra release step
- no risk of a stale checked-in baseline

As long as Plain's owned schema is mostly model tables plus convergence-managed indexes/constraints/defaults, runtime generation is a reasonable default.

The baseline artifact becomes interesting when one of these starts to matter more:

- self-hosted users commonly skip many releases
- release-to-release install determinism matters more than generator simplicity
- Plain wants a clearer upgrade support policy
- Plain starts owning more DB-native objects outside the model system

## Relationship to upgrade policy

This only helps with old history if Plain chooses to use it that way.

- **Without a support policy:** the baseline is just a fast fresh-install artifact.
- **With a support policy:** the baseline can become the line that separates "still supported for upgrade" from "too old; install a newer baseline first or upgrade through an intermediate release."

That policy choice is separate from the technical mechanism.

## Sketch of a release lifecycle

```text
Release N:
  - generate baseline.sql from current models
  - ship post-baseline migrations normally

Fresh install on Release N:
  - load baseline.sql
  - run convergence

Upgrade from a supported older install:
  - run incremental migrations since its current version
  - run convergence
```

Any application seed/init data remains a separate app-level concern outside this design.

## Key point

If this feature exists, the baseline should be understood as:

- **derived from models**
- **used mainly for fresh installs**
- **optionally used to define a support boundary**

It should not replace incremental migrations for supported upgrades.
