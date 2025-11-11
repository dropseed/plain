# plain-jobs changelog

## [0.38.1](https://github.com/dropseed/plain/releases/plain-jobs@0.38.1) (2025-11-11)

### What's changed

- Updated imports to use explicit `plain.models.expressions` instead of accessing `Case`, `When`, and `F` through `plain.models` namespace ([e9edf61c6b](https://github.com/dropseed/plain/commit/e9edf61c6b))

### Upgrade instructions

- No changes required

## [0.38.0](https://github.com/dropseed/plain/releases/plain-jobs@0.38.0) (2025-11-09)

### What's changed

- Renamed `unique_key` to `concurrency_key` throughout the API for better clarity about its purpose as a grouping identifier ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Added `should_enqueue()` hook for implementing custom concurrency limits and rate limiting ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Added PostgreSQL advisory lock support to prevent race conditions when checking concurrency limits ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Added `DeferJob` exception for signaling jobs should be re-tried later without counting as errors ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Added helper methods `get_requested_jobs()` and `get_processing_jobs()` for querying jobs by concurrency key ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Renamed job configuration methods from `get_*()` to `default_*()` (e.g., `get_queue()` → `default_queue()`) to better indicate they provide defaults that can be overridden ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Renamed `get_retry_delay()` to `calculate_retry_delay()` for better semantic clarity ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Changed field types for `priority`, `retries`, and `retry_attempt` from `IntegerField` to `SmallIntegerField` for better database efficiency ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))
- Added `DEFERRED` status to job results for jobs that were deferred and will be retried ([01b6986d79](https://github.com/dropseed/plain/commit/01b6986d79))

### Upgrade instructions

- Rename `unique_key` parameter to `concurrency_key` in all `run_in_worker()` calls
- Rename job method `get_unique_key()` to `default_concurrency_key()` if you've overridden it
- Rename job methods: `get_queue()` → `default_queue()`, `get_priority()` → `default_priority()`, `get_retries()` → `default_retries()`
- Rename `get_retry_delay()` to `calculate_retry_delay()` if you've overridden it

## [0.37.6](https://github.com/dropseed/plain/releases/plain-jobs@0.37.6) (2025-11-04)

### What's changed

- Removed info-level logging when a duplicate job is detected with a unique key to reduce log noise ([b6ad845180](https://github.com/dropseed/plain/commit/b6ad845180))

### Upgrade instructions

- No changes required

## [0.37.5](https://github.com/dropseed/plain/releases/plain-jobs@0.37.5) (2025-11-04)

### What's changed

- Added info-level logging when a duplicate job is detected with a unique key, making it easier to debug and monitor job deduplication ([8a9253bc63](https://github.com/dropseed/plain/commit/8a9253bc63))

### Upgrade instructions

- No changes required

## [0.37.4](https://github.com/dropseed/plain/releases/plain-jobs@0.37.4) (2025-11-03)

### What's changed

- Fixed migration documentation to reference correct renamed commands: `plain db shell` instead of `plain models db-shell` and `plain migrations prune` instead of `plain migrate --prune` ([b293750f6f](https://github.com/dropseed/plain/commit/b293750f6f))

### Upgrade instructions

- No changes required

## [0.37.3](https://github.com/dropseed/plain/releases/plain-jobs@0.37.3) (2025-11-03)

### What's changed

- No functional changes in this release

### Upgrade instructions

- No changes required

## [0.37.2](https://github.com/dropseed/plain/releases/plain-jobs@0.37.2) (2025-10-31)

### What's changed

- Added BSD-3-Clause license specification to package metadata ([8477355e65](https://github.com/dropseed/plain/commit/8477355e65))

### Upgrade instructions

- No changes required

## [0.37.1](https://github.com/dropseed/plain/releases/plain-jobs@0.37.1) (2025-10-24)

### What's changed

- Fixed admin interface filter functionality to correctly use `preset` instead of `display` for filtering job results ([26fde7d562](https://github.com/dropseed/plain/commit/26fde7d562))

### Upgrade instructions

- No changes required

## [0.37.0](https://github.com/dropseed/plain/releases/plain-jobs@0.37.0) (2025-10-22)

### What's changed

- Added `JobMiddleware` abstract base class for creating custom job middleware ([29e5c6df1a](https://github.com/dropseed/plain/commit/29e5c6df1a))
- Changed "preparing to execute job" log message from `logger.info` to `logger.debug` to reduce log noise ([8e25856639](https://github.com/dropseed/plain/commit/8e25856639))

### Upgrade instructions

- If you have custom job middleware, update them to inherit from `JobMiddleware` and implement the `process_job()` method instead of `__call__()`

## [0.36.3](https://github.com/dropseed/plain/releases/plain-jobs@0.36.3) (2025-10-20)

### What's changed

- Added garbage collection back to worker processes after job completion to help manage memory usage ([aafe3ace02](https://github.com/dropseed/plain/commit/aafe3ace02))

### Upgrade instructions

- No changes required

## [0.36.2](https://github.com/dropseed/plain/releases/plain-jobs@0.36.2) (2025-10-20)

### What's changed

- Fixed scheduled job detection logic to properly check for `None` instead of checking for list type when determining if a duplicate job was scheduled ([09e45fd96b](https://github.com/dropseed/plain/commit/09e45fd96b))

### Upgrade instructions

- No changes required

## [0.36.1](https://github.com/dropseed/plain/releases/plain-jobs@0.36.1) (2025-10-20)

### What's changed

- Fixed `run_in_worker()` to properly return `None` when a duplicate job is detected with a unique key, instead of returning the list of in-progress jobs ([5d7df365d6](https://github.com/dropseed/plain/commit/5d7df365d6))

### Upgrade instructions

- No changes required

## [0.36.0](https://github.com/dropseed/plain/releases/plain-jobs@0.36.0) (2025-10-17)

### What's changed

- Removed internal memory optimization attempts including manual garbage collection and object deletion in worker processes ([c7064ba329](https://github.com/dropseed/plain/commit/c7064ba329))
- Increased worker sleep interval from 0.1s to 0.5s when no jobs are available, reducing CPU usage during idle periods ([c7064ba329](https://github.com/dropseed/plain/commit/c7064ba329))

### Upgrade instructions

- No changes required

## [0.35.1](https://github.com/dropseed/plain/releases/plain-jobs@0.35.1) (2025-10-17)

### What's changed

- The `run_in_worker()` method now returns `None` when a duplicate job is detected instead of attempting to return the list of in-progress jobs ([72f48d21bc](https://github.com/dropseed/plain/commit/72f48d21bc))
- Fixed type annotations for `run_in_worker()` to properly indicate it can return `JobRequest | None` ([72f48d21bc](https://github.com/dropseed/plain/commit/72f48d21bc))
- The `retry_job()` method now properly handles explicit `delay=0` parameter to intentionally retry immediately ([72f48d21bc](https://github.com/dropseed/plain/commit/72f48d21bc))
- Fixed type annotations for `retry_job()` to properly indicate it can return `JobRequest | None` ([72f48d21bc](https://github.com/dropseed/plain/commit/72f48d21bc))

### Upgrade instructions

- No changes required

## [0.35.0](https://github.com/dropseed/plain/releases/plain-jobs@0.35.0) (2025-10-17)

### What's changed

- The `Job` base class is now an abstract base class requiring implementation of the `run()` method ([e34282bba8](https://github.com/dropseed/plain/commit/e34282bba8))
- Job worker processes now properly initialize the Plain framework before processing jobs, fixing potential startup issues ([c4551d1b84](https://github.com/dropseed/plain/commit/c4551d1b84))
- The `plain jobs list` command now displays job descriptions from docstrings in a cleaner format ([4b6881a49e](https://github.com/dropseed/plain/commit/4b6881a49e))
- Job requests in the admin interface are now ordered by priority, start time, and created time to match worker processing order ([c18f0e3fb6](https://github.com/dropseed/plain/commit/c18f0e3fb6))
- The `ClearCompleted` chore has been refactored to use the new abstract base class pattern ([c4466d3c60](https://github.com/dropseed/plain/commit/c4466d3c60))

### Upgrade instructions

- No changes required

## [0.34.0](https://github.com/dropseed/plain/releases/plain-jobs@0.34.0) (2025-10-13)

### What's changed

- Added `--reload` flag to `plain jobs worker` command for automatic reloading when code changes are detected ([f3db87e9aa](https://github.com/dropseed/plain/commit/f3db87e9aa))
- Worker reloader now only watches `.py` and `.env*` files, not HTML files ([f2f31c288b](https://github.com/dropseed/plain/commit/f2f31c288b))

### Upgrade instructions

- Custom autoreloaders for development are no longer needed -- use the built-in `--reload` flag instead

## [0.33.0](https://github.com/dropseed/plain/releases/plain-jobs@0.33.0) (2025-10-10)

### What's changed

- Renamed package from `plain.worker` to `plain.jobs` ([24219856e0](https://github.com/dropseed/plain/commit/24219856e0))

### Upgrade instructions

- Update any imports from `plain.worker` to `plain.jobs` (e.g., `from plain.worker import Job` becomes `from plain.jobs import Job`)
- Change worker commands from `plain worker run` to `plain jobs worker`
- Check updated settings names

## [0.32.0](https://github.com/dropseed/plain/releases/plain-jobs@0.32.0) (2025-10-07)

### What's changed

- Models now use `model_options` instead of `_meta` for accessing model configuration like `package_label` and `model_name` ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0))
- Model configuration now uses `model_options = models.Options()` instead of `class Meta` ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- QuerySet types now properly use `Self` return type for better type checking ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Removed unnecessary type ignore comments now that QuerySet is properly typed ([2578301](https://github.com/dropseed/plain/commit/2578301819))

### Upgrade instructions

- No changes required

## [0.31.1](https://github.com/dropseed/plain/releases/plain-jobs@0.31.1) (2025-10-06)

### What's changed

- Updated dependency resolution to use newer compatible versions of `plain` and `plain.models`

### Upgrade instructions

- No changes required

## [0.31.0](https://github.com/dropseed/plain/releases/plain-jobs@0.31.0) (2025-09-25)

### What's changed

- The jobs autodiscovery now includes `app.jobs` modules in addition to package jobs modules ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461))

### Upgrade instructions

- No changes required

## [0.30.0](https://github.com/dropseed/plain/releases/plain-jobs@0.30.0) (2025-09-19)

### What's changed

- The `Job` model has been renamed to `JobProcess` for better clarity ([986c914](https://github.com/dropseed/plain/commit/986c914))
- The `job_uuid` field in JobResult has been renamed to `job_process_uuid` to match the model rename ([986c914](https://github.com/dropseed/plain/commit/986c914))
- Admin interface now shows "Job processes" as the section title instead of "Jobs" ([986c914](https://github.com/dropseed/plain/commit/986c914))

### Upgrade instructions

- Run `plain migrate` to apply the database migration that renames the Job model to JobProcess
- If you have any custom code that directly references the `Job` model (different than the `Job` base class for job type definitions), update it to use `JobProcess` instead
- If you have any code that accesses the `job_uuid` field on JobResult instances, update it to use `job_process_uuid`

## [0.29.0](https://github.com/dropseed/plain/releases/plain-jobs@0.29.0) (2025-09-12)

### What's changed

- Model managers have been renamed from `.objects` to `.query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Manager functionality has been merged into QuerySet classes ([bbaee93](https://github.com/dropseed/plain/commit/bbaee93839))
- Models now use `Meta.queryset_class` instead of separate manager configuration ([6b60a00](https://github.com/dropseed/plain/commit/6b60a00731))

### Upgrade instructions

- Update all model queries to use `.query` instead of `.objects` (e.g., `Job.query.all()` becomes `Job.query.all()`)

## [0.28.1](https://github.com/dropseed/plain/releases/plain-jobs@0.28.1) (2025-09-10)

### What's changed

- Fixed log context method in worker middleware to use `include_context` instead of `with_context` ([755f873](https://github.com/dropseed/plain/commit/755f873986))

### Upgrade instructions

- No changes required

## [0.28.0](https://github.com/dropseed/plain/releases/plain-jobs@0.28.0) (2025-09-09)

### What's changed

- Improved logging middleware to use context manager pattern for cleaner job context handling ([ea7c953](https://github.com/dropseed/plain/commit/ea7c9537e3))
- Updated minimum Python requirement to 3.13 ([d86e307](https://github.com/dropseed/plain/commit/d86e307efb))
- Added explicit nav_icon definitions to admin views to ensure consistent icon display ([2aac07d](https://github.com/dropseed/plain/commit/2aac07de4e))

### Upgrade instructions

- No changes required

## [0.27.1](https://github.com/dropseed/plain/releases/plain-jobs@0.27.1) (2025-08-27)

### What's changed

- Jobs are now marked as cancelled when the worker process is killed or fails unexpectedly ([e73ca53](https://github.com/dropseed/plain/commit/e73ca53c3d))

### Upgrade instructions

- No changes required

## [0.27.0](https://github.com/dropseed/plain/releases/plain-jobs@0.27.0) (2025-08-22)

### What's changed

- Added support for date and datetime job parameters with proper serialization/deserialization ([7bb5ab0911](https://github.com/dropseed/plain/commit/7bb5ab0911))
- Improved job priority documentation to clarify that higher numbers run first ([73271b5bf0](https://github.com/dropseed/plain/commit/73271b5bf0))
- Updated admin interface with consolidated navigation icons at the section level ([5a6479ac79](https://github.com/dropseed/plain/commit/5a6479ac79))
- Enhanced admin views to use cached object properties for better performance ([bd0507a72c](https://github.com/dropseed/plain/commit/bd0507a72c))

### Upgrade instructions

- No changes required

## [0.26.0](https://github.com/dropseed/plain/releases/plain-jobs@0.26.0) (2025-08-19)

### What's changed

- Improved CSRF token handling in admin forms by removing manual `csrf_input` in favor of automatic Sec-Fetch-Site header validation ([955150800c](https://github.com/dropseed/plain/commit/955150800c))
- Enhanced README documentation with comprehensive examples, table of contents, and detailed sections covering job parameters, scheduling, monitoring, and FAQs ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))
- Updated package description to be more descriptive: "Process background jobs with a database-driven worker" ([4ebecd1856](https://github.com/dropseed/plain/commit/4ebecd1856))

### Upgrade instructions

- No changes required

## [0.25.1](https://github.com/dropseed/plain/releases/plain-jobs@0.25.1) (2025-07-23)

### What's changed

- Added Bootstrap icons to admin interface for worker job views ([9e9f8b0](https://github.com/dropseed/plain/commit/9e9f8b0e2ccc3174f05034e6e908bb26345e1a5c))
- Removed the description field from admin views ([8d2352d](https://github.com/dropseed/plain/commit/8d2352db94277ddd87b6a480783c9f740b6e806f))

### Upgrade instructions

- No changes required

## [0.25.0](https://github.com/dropseed/plain/releases/plain-jobs@0.25.0) (2025-07-22)

### What's changed

- Removed `pk` alias and auto fields in favor of a single automatic `id` PrimaryKeyField ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6aef126a15e48b5f85e0652adf841eb7b5c))
- Admin interface methods now use `target_ids` parameter instead of `target_pks` for batch actions
- Model instance registry now uses `.id` instead of `.pk` for Global ID generation
- Updated database migrations to use `models.PrimaryKeyField()` instead of `models.BigAutoField()`

### Upgrade instructions

- No changes required

## [0.24.0](https://github.com/dropseed/plain/releases/plain-jobs@0.24.0) (2025-07-18)

### What's changed

- Added OpenTelemetry tracing support to job processing system ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0418))
- Job requests now capture trace context when queued from traced operations
- Job execution creates proper consumer spans linked to the original producer trace
- Added `trace_id` and `span_id` fields to JobRequest, Job, and JobResult models for trace correlation

### Upgrade instructions

- Run `plain migrate` to apply new database migration that adds trace context fields to worker tables

## [0.23.0](https://github.com/dropseed/plain/releases/plain-jobs@0.23.0) (2025-07-18)

### What's changed

- Migrations have been reset and consolidated into a single initial migration ([484f1b6e93](https://github.com/dropseed/plain/commit/484f1b6e93))

### Upgrade instructions

- Run `plain migrate --prune plainworker` to remove old migration records and apply the consolidated migration

## [0.22.5](https://github.com/dropseed/plain/releases/plain-jobs@0.22.5) (2025-06-24)

### What's changed

- No functional changes. This release only updates internal documentation (CHANGELOG) and contains no code modifications that impact users ([82710c3](https://github.com/dropseed/plain/commit/82710c3), [9a1963d](https://github.com/dropseed/plain/commit/9a1963d), [e1f5dd3](https://github.com/dropseed/plain/commit/e1f5dd3)).

### Upgrade instructions

- No changes required
