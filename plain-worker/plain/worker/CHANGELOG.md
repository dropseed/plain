# plain-worker changelog

## [0.27.0](https://github.com/dropseed/plain/releases/plain-worker@0.27.0) (2025-08-22)

### What's changed

- Added support for date and datetime job parameters with proper serialization/deserialization ([7bb5ab0911](https://github.com/dropseed/plain/commit/7bb5ab0911))
- Improved job priority documentation to clarify that higher numbers run first ([73271b5bf0](https://github.com/dropseed/plain/commit/73271b5bf0))
- Updated admin interface with consolidated navigation icons at the section level ([5a6479ac79](https://github.com/dropseed/plain/commit/5a6479ac79))
- Enhanced admin views to use cached object properties for better performance ([bd0507a72c](https://github.com/dropseed/plain/commit/bd0507a72c))

### Upgrade instructions

- No changes required

## [0.26.0](https://github.com/dropseed/plain/releases/plain-worker@0.26.0) (2025-08-19)

### What's changed

- Improved CSRF token handling in admin forms by removing manual `csrf_input` in favor of automatic Sec-Fetch-Site header validation ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Enhanced README documentation with comprehensive examples, table of contents, and detailed sections covering job parameters, scheduling, monitoring, and FAQs ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))
- Updated package description to be more descriptive: "Process background jobs with a database-driven worker" ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.25.1](https://github.com/dropseed/plain/releases/plain-worker@0.25.1) (2025-07-23)

### What's changed

- Added Bootstrap icons to admin interface for worker job views ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2ccc3174f05034e6e908bb26345e1a5c))
- Removed the description field from admin views ([8d2352d](https://github.com/dropseed/plain/commit/8d2352db94277ddd87b6a480783c9f740b6e806f))

### Upgrade instructions

- No changes required

## [0.25.0](https://github.com/dropseed/plain/releases/plain-worker@0.25.0) (2025-07-22)

### What's changed

- Removed `pk` alias and auto fields in favor of a single automatic `id` PrimaryKeyField ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef126a15e48b5f85e0652adf841eb7b5c))
- Admin interface methods now use `target_ids` parameter instead of `target_pks` for batch actions
- Model instance registry now uses `.id` instead of `.pk` for Global ID generation
- Updated database migrations to use `models.PrimaryKeyField()` instead of `models.BigAutoField()`

### Upgrade instructions

- No changes required

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
