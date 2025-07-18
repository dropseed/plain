# plain-worker changelog

## [0.24.0](https://github.com/dropseed/plain/releases/plain-worker@0.24.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support to job processing system ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Job requests now capture trace context when queued from traced operations
- Job execution creates proper consumer spans linked to the original producer trace
- Added `trace_id` and `span_id` fields to JobRequest, Job, and JobResult models for trace correlation

### Upgrade instructions

- Run `plain migrate` to apply new database migration that adds trace context fields to worker tables

## [0.23.0](https://github.com/dropseed/plain/releases/plain-worker@0.23.0) (2025-07-18)

### What's changed

- Migrations have been reset and consolidated into a single initial migration ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainworker` to remove old migration records and apply the consolidated migration

## [0.22.5](https://github.com/dropseed/plain/releases/plain-worker@0.22.5) (2025-06-24)

### What's changed

- No functional changes. This release only updates internal documentation (CHANGELOG) and contains no code modifications that impact users ([82710c3](https://github.com/dropseed/plain/commit/82710c3), [9a1963d](https://github.com/dropseed/plain/commit/9a1963d), [e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3)).

### Upgrade instructions

- No changes required
