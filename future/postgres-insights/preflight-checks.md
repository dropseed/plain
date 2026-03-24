---
related:
  - diagnose-command
---

# Preflight integration

Promote diagnose checks that indicate real problems to preflight warnings:

- Unused indexes (wasted write overhead)
- Duplicate indexes
- Sequence exhaustion (will cause hard failure)
- TX ID wraparound danger
- Schema drift (see `migrations-schema-check` in data layer arc)

These run during `plain check` / deploy. Operational checks (connections, locks, long queries) stay CLI-only — they're point-in-time diagnostics, not deploy gates.
