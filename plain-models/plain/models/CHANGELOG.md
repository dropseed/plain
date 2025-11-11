# plain-models changelog

## [0.57.0](https://github.com/dropseed/plain/releases/plain-models@0.57.0) (2025-11-11)

### What's changed

- The `plain.models` import namespace has been cleaned up to only include the most commonly used APIs for defining models ([e9edf61](https://github.com/dropseed/plain/commit/e9edf61c6b), [22b798c](https://github.com/dropseed/plain/commit/22b798cf57), [d5a2167](https://github.com/dropseed/plain/commit/d5a2167d14))
- Field classes are now descriptors themselves, eliminating the need for a separate descriptor class ([93f8bd7](https://github.com/dropseed/plain/commit/93f8bd72e9))
- Model initialization no longer accepts positional arguments - all field values must be passed as keyword arguments ([685f99a](https://github.com/dropseed/plain/commit/685f99a33a))
- Attempting to set a primary key during model initialization now raises a clear `ValueError` instead of silently accepting the value ([ecf490c](https://github.com/dropseed/plain/commit/ecf490cb2a))

### Upgrade instructions

- Import advanced query features from their specific modules instead of `plain.models`:
    - Aggregates: `from plain.models.aggregates import Avg, Count, Max, Min, Sum`
    - Expressions: `from plain.models.expressions import Case, Exists, Expression, ExpressionWrapper, F, Func, OuterRef, Subquery, Value, When, Window`
    - Query utilities: `from plain.models.query import Prefetch, prefetch_related_objects`
    - Lookups: `from plain.models.lookups import Lookup, Transform`
- Remove any positional arguments in model instantiation and use keyword arguments instead (e.g., `User("John", "Doe")` becomes `User(first_name="John", last_name="Doe")`)

## [0.56.1](https://github.com/dropseed/plain/releases/plain-models@0.56.1) (2025-11-03)

### What's changed

- Fixed preflight checks and README to reference the correct new command names (`plain db shell` and `plain migrations prune`) instead of the old `plain models` commands ([b293750](https://github.com/dropseed/plain/commit/b293750f6f))

### Upgrade instructions

- No changes required

## [0.56.0](https://github.com/dropseed/plain/releases/plain-models@0.56.0) (2025-11-03)

### What's changed

- The CLI has been reorganized into separate `plain db` and `plain migrations` command groups for better organization ([7910a06](https://github.com/dropseed/plain/commit/7910a06e86132ef1fc1720bd960916ee009e27cf))
- The `plain models` command group has been removed - use `plain db` and `plain migrations` instead ([7910a06](https://github.com/dropseed/plain/commit/7910a06e86132ef1fc1720bd960916ee009e27cf))
- The `plain backups` command group has been removed - use `plain db backups` instead ([dd87b76](https://github.com/dropseed/plain/commit/dd87b762babb370751cffdc27be3c6a53c6c98b4))
- Database backup output has been simplified to show file size and timestamp on a single line ([765d118](https://github.com/dropseed/plain/commit/765d1184c6d0bdb1f91a85bf511d049da74a6276))

### Upgrade instructions

- Replace `plain models db-shell` with `plain db shell`
- Replace `plain models db-wait` with `plain db wait`
- Replace `plain models list` with `plain db list` (note: this command was moved to the main plain package)
- Replace `plain models show-migrations` with `plain migrations list`
- Replace `plain models prune-migrations` with `plain migrations prune`
- Replace `plain models squash-migrations` with `plain migrations squash`
- Replace `plain backups` commands with `plain db backups` (e.g., `plain backups list` becomes `plain db backups list`)
- The shortcuts `plain makemigrations` and `plain migrate` continue to work unchanged

## [0.55.1](https://github.com/dropseed/plain/releases/plain-models@0.55.1) (2025-10-31)

### What's changed

- Added `license = "BSD-3-Clause"` to package metadata ([8477355](https://github.com/dropseed/plain/commit/8477355e65b62be6e4618bcc814c912e050dc388))

### Upgrade instructions

- No changes required

## [0.55.0](https://github.com/dropseed/plain/releases/plain-models@0.55.0) (2025-10-24)

### What's changed

- The plain-models package now uses an explicit `package_label = "plainmodels"` to avoid conflicts with other packages ([d1783dd](https://github.com/dropseed/plain/commit/d1783dd564cb48380e59cb4598722649a7d9574f))
- Fixed migration loader to correctly check for `plainmodels` package label instead of `models` ([c41d11c](https://github.com/dropseed/plain/commit/c41d11c70d02bab59c6951ef1074b13a392d04a6))

### Upgrade instructions

- No changes required

## [0.54.0](https://github.com/dropseed/plain/releases/plain-models@0.54.0) (2025-10-22)

### What's changed

- SQLite migrations are now always run separately instead of in atomic batches, fixing issues with foreign key constraint handling ([5082453](https://github.com/dropseed/plain/commit/508245375960f694cfac4e17a6bfbb2301969a5c))

### Upgrade instructions

- No changes required

## [0.53.1](https://github.com/dropseed/plain/releases/plain-models@0.53.1) (2025-10-20)

### What's changed

- Internal packaging update to use `dependency-groups` standard instead of `tool.uv.dev-dependencies` ([1b43a3a](https://github.com/dropseed/plain/commit/1b43a3a272))

### Upgrade instructions

- No changes required

## [0.53.0](https://github.com/dropseed/plain/releases/plain-models@0.53.0) (2025-10-12)

### What's changed

- Added new `plain models prune-migrations` command to identify and remove stale migration records from the database ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))
- The `--prune` option has been removed from `plain migrate` command in favor of the dedicated `prune-migrations` command ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))
- Added new preflight check `models.prunable_migrations` that warns about stale migration records in the database ([9b43617](https://github.com/dropseed/plain/commit/9b4361765c))
- The `show-migrations` command no longer displays prunable migrations in its output ([998aa49](https://github.com/dropseed/plain/commit/998aa49140))

### Upgrade instructions

- Replace any usage of `plain migrate --prune` with the new `plain models prune-migrations` command

## [0.52.0](https://github.com/dropseed/plain/releases/plain-models@0.52.0) (2025-10-10)

### What's changed

- The `plain migrate` command now shows detailed operation descriptions and SQL statements for each migration step, replacing the previous verbosity levels with a cleaner `--quiet` flag ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))
- Migration output format has been improved to display each operation's description and the actual SQL being executed, making it easier to understand what changes are being made to the database ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))
- The `-v/--verbosity` option has been removed from `plain migrate` in favor of the simpler `--quiet` flag for suppressing output ([d6b041bd24](https://github.com/dropseed/plain/commit/d6b041bd24))

### Upgrade instructions

- Replace any usage of `-v` or `--verbosity` flags in `plain migrate` commands with `--quiet` if you want to suppress migration output

## [0.51.1](https://github.com/dropseed/plain/releases/plain-models@0.51.1) (2025-10-08)

### What's changed

- Fixed a bug in `Subquery` and `Exists` expressions that was using the old `query` attribute name instead of `sql_query` when extracting the SQL query from a QuerySet ([79ca52d](https://github.com/dropseed/plain/commit/79ca52d32e))

### Upgrade instructions

- No changes required

## [0.51.0](https://github.com/dropseed/plain/releases/plain-models@0.51.0) (2025-10-07)

### What's changed

- Model metadata has been split into two separate descriptors: `model_options` for user-defined configuration and `_model_meta` for internal metadata ([73ba469](https://github.com/dropseed/plain/commit/73ba469ba0), [17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- The `_meta` attribute has been replaced with `model_options` for user-defined options like indexes, constraints, and database settings ([17a378d](https://github.com/dropseed/plain/commit/17a378dcfb))
- Custom QuerySets are now assigned directly to the `query` class attribute instead of using `Meta.queryset_class` ([2578301](https://github.com/dropseed/plain/commit/2578301819))
- Added comprehensive type improvements to model metadata and related fields for better IDE support ([3b477a0](https://github.com/dropseed/plain/commit/3b477a0d43))

### Upgrade instructions

- Replace `Meta.queryset_class = CustomQuerySet` with `query = CustomQuerySet()` as a class attribute on your models
- Replace `class Meta:` with `model_options = models.Options(...)` in your models

## [0.50.0](https://github.com/dropseed/plain/releases/plain-models@0.50.0) (2025-10-06)

### What's changed

- Added comprehensive type annotations throughout plain-models, improving IDE support and type checking capabilities ([ea1a7df](https://github.com/dropseed/plain/commit/ea1a7df622), [f49ee32](https://github.com/dropseed/plain/commit/f49ee32a90), [369353f](https://github.com/dropseed/plain/commit/369353f9d6), [13b7d16](https://github.com/dropseed/plain/commit/13b7d16f8d), [e23a0ca](https://github.com/dropseed/plain/commit/e23a0cae7c), [02d8551](https://github.com/dropseed/plain/commit/02d85518f0))
- The `QuerySet` class is now generic and the `model` parameter is now required in the `__init__` method ([719e792](https://github.com/dropseed/plain/commit/719e792c96))
- Database wrapper classes have been renamed for consistency: `DatabaseWrapper` classes are now named `MySQLDatabaseWrapper`, `PostgreSQLDatabaseWrapper`, and `SQLiteDatabaseWrapper` ([5a39e85](https://github.com/dropseed/plain/commit/5a39e851e5))
- The plain-models package now has 100% type annotation coverage and is validated in CI to prevent regressions

### Upgrade instructions

- No changes required

## [0.49.2](https://github.com/dropseed/plain/releases/plain-models@0.49.2) (2025-10-02)

### What's changed

- Updated dependency to use the latest plain package version

### Upgrade instructions

- No changes required

## [0.49.1](https://github.com/dropseed/plain/releases/plain-models@0.49.1) (2025-09-29)

### What's changed

- Fixed `get_field_display()` method to accept field name as string instead of field object ([1c20405](https://github.com/dropseed/plain/commit/1c20405ac3))

### Upgrade instructions

- No changes required

## [0.49.0](https://github.com/dropseed/plain/releases/plain-models@0.49.0) (2025-09-29)

### What's changed

- Model exceptions (`FieldDoesNotExist`, `FieldError`, `ObjectDoesNotExist`, `MultipleObjectsReturned`, `EmptyResultSet`, `FullResultSet`) have been moved from `plain.exceptions` to `plain.models.exceptions` ([1c02564](https://github.com/dropseed/plain/commit/1c02564561))
- The `get_FOO_display()` methods for fields with choices have been replaced with a single `get_field_display(field_name)` method ([e796e71](https://github.com/dropseed/plain/commit/e796e71e02))
- The `get_next_by_*` and `get_previous_by_*` methods for date fields have been removed ([3a5b8a8](https://github.com/dropseed/plain/commit/3a5b8a89d1))
- The `id` primary key field is now defined directly on the Model base class instead of being added dynamically via Options ([e164dc7](https://github.com/dropseed/plain/commit/e164dc7982))
- Model `DoesNotExist` and `MultipleObjectsReturned` exceptions now use descriptors for better performance ([8f54ea3](https://github.com/dropseed/plain/commit/8f54ea3a62))

### Upgrade instructions

- Update imports for model exceptions from `plain.exceptions` to `plain.models.exceptions` (e.g., `from plain.exceptions import ObjectDoesNotExist` becomes `from plain.models.exceptions import ObjectDoesNotExist`)
- Replace any usage of `instance.get_FOO_display()` with `instance.get_field_display("FOO")` where FOO is the field name
- Remove any usage of `get_next_by_*` and `get_previous_by_*` methods - use QuerySet ordering instead (e.g., `Model.query.filter(date__gt=obj.date).order_by("date").first()`)

## [0.48.0](https://github.com/dropseed/plain/releases/plain-models@0.48.0) (2025-09-26)

### What's changed

- Migrations now run in a single transaction by default for databases that support transactional DDL, providing all-or-nothing migration batches for better safety and consistency ([6d0c105](https://github.com/dropseed/plain/commit/6d0c105fa9))
- Added `--atomic-batch/--no-atomic-batch` options to `plain migrate` to explicitly control whether migrations are run in a single transaction ([6d0c105](https://github.com/dropseed/plain/commit/6d0c105fa9))

### Upgrade instructions

- No changes required

## [0.47.0](https://github.com/dropseed/plain/releases/plain-models@0.47.0) (2025-09-25)

### What's changed

- The `QuerySet.query` property has been renamed to `QuerySet.sql_query` to better distinguish it from the `Model.query` manager interface ([d250eea](https://github.com/dropseed/plain/commit/d250eeac03))

### Upgrade instructions

- If you directly accessed the `QuerySet.query` property in your code (typically for advanced query manipulation or debugging), rename it to `QuerySet.sql_query`

## [0.46.1](https://github.com/dropseed/plain/releases/plain-models@0.46.1) (2025-09-25)

### What's changed

- Fixed `prefetch_related` for reverse foreign key relationships by correctly handling related managers in the prefetch query process ([2c04e80](https://github.com/dropseed/plain/commit/2c04e80dcd))

### Upgrade instructions

- No changes required

## [0.46.0](https://github.com/dropseed/plain/releases/plain-models@0.46.0) (2025-09-25)

### What's changed

- The preflight system has been completely reworked with a new `PreflightResult` class that unifies messages and hints into a single `fix` field, providing clearer and more actionable error messages ([b0b610d](https://github.com/dropseed/plain/commit/b0b610d461), [c7cde12](https://github.com/dropseed/plain/commit/c7cde12149))
- Preflight check IDs have been renamed to use descriptive names instead of numbers for better clarity (e.g., `models.E003` becomes `models.duplicate_many_to_many_relations`) ([cd96c97](https://github.com/dropseed/plain/commit/cd96c97b25))
- Removed deprecated field types: `CommaSeparatedIntegerField`, `IPAddressField`, and `NullBooleanField` ([345295dc](https://github.com/dropseed/plain/commit/345295dc8a))
- Removed `system_check_deprecated_details` and `system_check_removed_details` from fields ([e3a7d2dd](https://github.com/dropseed/plain/commit/e3a7d2dd10))

### Upgrade instructions

- Remove any usage of the deprecated field types `CommaSeparatedIntegerField`, `IPAddressField`, and `NullBooleanField` - use `CharField`, `GenericIPAddressField`, and `BooleanField(null=True)` respectively

## [0.45.0](https://github.com/dropseed/plain/releases/plain-models@0.45.0) (2025-09-21)

### What's changed

- Added unlimited varchar support to SQLite - CharField fields without a max_length now generate `varchar` columns instead of `varchar()` with no length specified ([c5c0c3a](https://github.com/dropseed/plain/commit/c5c0c3a743))

### Upgrade instructions

- No changes required

## [0.44.0](https://github.com/dropseed/plain/releases/plain-models@0.44.0) (2025-09-19)

### What's changed

- PostgreSQL backup restoration now drops and recreates the database instead of using `pg_restore --clean`, providing more reliable restoration by terminating active connections and ensuring a completely clean database state ([a8865fe](https://github.com/dropseed/plain/commit/a8865fe5d6))
- Added `_meta` type annotation to the `Model` class for improved type checking and IDE support ([387b92e](https://github.com/dropseed/plain/commit/387b92e08b))

### Upgrade instructions

- No changes required

## [0.43.0](https://github.com/dropseed/plain/releases/plain-models@0.43.0) (2025-09-12)

### What's changed

- The `related_name` parameter is now required for ForeignKey and ManyToManyField relationships if you want a reverse accessor. The `"+"` suffix to disable reverse relations has been removed, and automatic `_set` suffixes are no longer generated ([89fa03979f](https://github.com/dropseed/plain/commit/89fa03979f))
- Refactored related descriptors and managers for better internal organization and type safety ([9f0b03957a](https://github.com/dropseed/plain/commit/9f0b03957a))
- Added docstrings and return type annotations to model `query` property and related manager methods for improved developer experience ([544d85b60b](https://github.com/dropseed/plain/commit/544d85b60b))

### Upgrade instructions

- Remove any `related_name="+"` usage - if you don't want a reverse accessor, simply omit the `related_name` parameter entirely
- Update any code that relied on automatic `_set` suffixes - these are no longer generated, so you must use explicit `related_name` values
- Add explicit `related_name` arguments to all ForeignKey and ManyToManyField definitions where you want reverse access (e.g., `models.ForeignKey(User, on_delete=models.CASCADE, related_name="articles")`)
- Consider removing `related_name` arguments that are not used in practice

## [0.42.0](https://github.com/dropseed/plain/releases/plain-models@0.42.0) (2025-09-12)

### What's changed

- The model manager interface has been renamed from `.objects` to `.query` ([037a239](https://github.com/dropseed/plain/commit/037a239ef4))
- Manager functionality has been merged into QuerySet, simplifying the architecture - custom QuerySets can now be set directly via `Meta.queryset_class` ([bbaee93](https://github.com/dropseed/plain/commit/bbaee93839))
- The `objects` manager is now set directly on the Model class for better type checking ([fccc5be](https://github.com/dropseed/plain/commit/fccc5be13e))
- Database backups are now created automatically during migrations when in DEBUG mode ([c8023074](https://github.com/dropseed/plain/commit/c8023074e9))
- Removed several legacy manager features: `default_related_name`, `base_manager_name`, `creation_counter`, `use_in_migrations`, `auto_created`, and routing hints ([multiple commits](https://github.com/dropseed/plain/compare/plain-models@0.41.1...037a239ef4))

### Upgrade instructions

- Replace all usage of `Model.objects` with `Model.query` in your codebase (e.g., `User.objects.filter()` becomes `User.query.filter()`)
- If you have custom managers, convert them to custom QuerySets and set them using `Meta.queryset_class` instead of assigning to class attributes (if there is more than one custom manager on a class, invoke the new QuerySet class directly or add a shortcut on the Model using `@classmethod`)
- Remove any usage of the removed manager features: `default_related_name`, `base_manager_name`, manager `creation_counter`, `use_in_migrations`, `auto_created`, and database routing hints
- Any reverse accessors (typically `<related_model>_set` or defined by `related_name`) will now return a manager class for the additional `add()`, `remove()`, `clear()`, etc. methods and the regular queryset methods will be available via `.query` (e.g., `user.articles.first()` becomes `user.articles.query.first()`)

## [0.41.1](https://github.com/dropseed/plain/releases/plain-models@0.41.1) (2025-09-09)

### What's changed

- Improved stack trace filtering in OpenTelemetry spans to exclude internal plain/models frames, making debugging traces cleaner and more focused on user code ([5771dd5](https://github.com/dropseed/plain/commit/5771dd5))

### Upgrade instructions

- No changes required

## [0.41.0](https://github.com/dropseed/plain/releases/plain-models@0.41.0) (2025-09-09)

### What's changed

- Python 3.13 is now the minimum required version ([d86e307](https://github.com/dropseed/plain/commit/d86e307))
- Removed the `earliest()`, `latest()`, and `get_latest_by` model meta option - use `order_by().first()` and `order_by().last()` instead ([b6093a8](https://github.com/dropseed/plain/commit/b6093a8))
- Removed automatic ordering in `first()` and `last()` queryset methods - they now respect the existing queryset ordering without adding default ordering ([adc19a6](https://github.com/dropseed/plain/commit/adc19a6))
- Added code location attributes to database operation tracing, showing the source file, line number, and function where the query originated ([da36a17](https://github.com/dropseed/plain/commit/da36a17))

### Upgrade instructions

- Replace usage of `earliest()`, `latest()`, and model `Meta` `get_latest_by` queryset methods with equivalent `order_by().first()` or `order_by().last()` calls
- The `first()` and `last()` methods no longer automatically add ordering by `id` - explicitly add `.order_by()` to your querysets or `ordering` to your models `Meta` class if needed

## [0.40.1](https://github.com/dropseed/plain/releases/plain-models@0.40.1) (2025-09-03)

### What's changed

- Internal documentation updates for agent commands ([df3edbf0bd](https://github.com/dropseed/plain/commit/df3edbf0bd))

### Upgrade instructions

- No changes required

## [0.40.0](https://github.com/dropseed/plain/releases/plain-models@0.40.0) (2025-08-05)

### What's changed

- Foreign key fields now accept lazy objects (like `SimpleLazyObject` used for `request.user`) by automatically evaluating them ([eb78dcc76d](https://github.com/dropseed/plain/commit/eb78dcc76d))
- Added `--no-input` option to `plain migrate` command to skip user prompts ([0bdaf0409e](https://github.com/dropseed/plain/commit/0bdaf0409e))
- Removed the `plain models optimize-migration` command ([6e4131ab29](https://github.com/dropseed/plain/commit/6e4131ab29))
- Removed the `--fake-initial` option from `plain migrate` command ([6506a8bfb9](https://github.com/dropseed/plain/commit/6506a8bfb9))
- Fixed CLI help text to reference `plain` commands instead of `manage.py` ([8071854d61](https://github.com/dropseed/plain/commit/8071854d61))

### Upgrade instructions

- Remove any usage of `plain models optimize-migration` command - it is no longer available
- Remove any usage of `--fake-initial` option from `plain migrate` commands - it is no longer supported
- It is no longer necessary to do `user=request.user or None`, for example, when setting foreign key fields with a lazy object like `request.user`. These will now be automatically evaluated.

## [0.39.2](https://github.com/dropseed/plain/releases/plain-models@0.39.2) (2025-07-25)

### What's changed

- Fixed remaining `to_field_name` attribute usage in `ModelMultipleChoiceField` validation to use `id` directly ([26c80356d3](https://github.com/dropseed/plain/commit/26c80356d3))

### Upgrade instructions

- No changes required

## [0.39.1](https://github.com/dropseed/plain/releases/plain-models@0.39.1) (2025-07-22)

### What's changed

- Added documentation for sharing fields across models using Python class mixins ([cad3af01d2](https://github.com/dropseed/plain/commit/cad3af01d2))
- Added note about `PrimaryKeyField()` replacement requirement for migrations ([70ea931660](https://github.com/dropseed/plain/commit/70ea931660))

### Upgrade instructions

- No changes required

## [0.39.0](https://github.com/dropseed/plain/releases/plain-models@0.39.0) (2025-07-22)

### What's changed

- Models now use a single automatic `id` field as the primary key, replacing the previous `pk` alias and automatic field system ([4b8fa6a](https://github.com/dropseed/plain/commit/4b8fa6a))
- Removed the `to_field` option for ForeignKey - foreign keys now always reference the primary key of the related model ([7fc3c88](https://github.com/dropseed/plain/commit/7fc3c88))
- Removed the internal `from_fields` and `to_fields` system used for multi-column foreign keys ([0e9eda3](https://github.com/dropseed/plain/commit/0e9eda3))
- Removed the `parent_link` parameter on ForeignKey and ForeignObject ([6658647](https://github.com/dropseed/plain/commit/6658647))
- Removed `InlineForeignKeyField` from forms ([ede6265](https://github.com/dropseed/plain/commit/ede6265))
- Merged ForeignObject functionality into ForeignKey, simplifying the foreign key implementation ([e6d9aaa](https://github.com/dropseed/plain/commit/e6d9aaa))
- Cleaned up unused code in ForeignKey and fixed ForeignObjectRel imports ([b656ee6](https://github.com/dropseed/plain/commit/b656ee6))

### Upgrade instructions

- Replace any direct references to `pk` with `id` in your models and queries (e.g., `user.pk` becomes `user.id`)
- Remove any `to_field` arguments from ForeignKey definitions - they are no longer supported
- Remove any `parent_link=True` arguments from ForeignKey definitions - they are no longer supported
- Replace any usage of `InlineForeignKeyField` in forms with standard form fields
- `models.BigAutoField(auto_created=True, primary_key=True)` need to be replaced with `models.PrimaryKeyField()` in migrations

## [0.38.0](https://github.com/dropseed/plain/releases/plain-models@0.38.0) (2025-07-21)

### What's changed

- Added `get_or_none()` method to QuerySet which returns a single object matching the given arguments or None if no object is found ([48e07bf](https://github.com/dropseed/plain/commit/48e07bf))

### Upgrade instructions

- No changes required

## [0.37.0](https://github.com/dropseed/plain/releases/plain-models@0.37.0) (2025-07-18)

### What's changed

- Added OpenTelemetry instrumentation for database operations - all SQL queries now automatically generate OpenTelemetry spans with standardized attributes following semantic conventions ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0))
- Database operations in tests are now wrapped with tracing suppression to avoid generating telemetry noise during test execution ([b0224d0](https://github.com/dropseed/plain/commit/b0224d0))

### Upgrade instructions

- No changes required

## [0.36.0](https://github.com/dropseed/plain/releases/plain-models@0.36.0) (2025-07-18)

### What's changed

- Removed the `--merge` option from the `makemigrations` command ([d366663](https://github.com/dropseed/plain/commit/d366663))
- Improved error handling in the `restore-backup` command using Click's error system ([88f06c5](https://github.com/dropseed/plain/commit/88f06c5))

### Upgrade instructions

- No changes required

## [0.35.0](https://github.com/dropseed/plain/releases/plain-models@0.35.0) (2025-07-07)

### What's changed

- Added the `plain models list` CLI command which prints a nicely formatted list of all installed models, including their table name, fields, and originating package. You can pass package labels to filter the output or use the `--app-only` flag to only show first-party app models ([1bc40ce](https://github.com/dropseed/plain/commit/1bc40ce)).
- The MySQL backend no longer enforces a strict `mysqlclient >= 1.4.3` version check and had several unused constraint-handling methods removed, reducing boilerplate and improving compatibility with a wider range of `mysqlclient` versions ([6322400](https://github.com/dropseed/plain/commit/6322400), [67f21f6](https://github.com/dropseed/plain/commit/67f21f6)).

### Upgrade instructions

- No changes required

## [0.34.4](https://github.com/dropseed/plain/releases/plain-models@0.34.4) (2025-07-02)

### What's changed

- The built-in `on_delete` behaviors (`CASCADE`, `PROTECT`, `RESTRICT`, `SET_NULL`, `SET_DEFAULT`, and the callables returned by `SET(...)`) no longer receive the legacy `using` argument. Their signatures are now `(collector, field, sub_objs)` ([20325a1](https://github.com/dropseed/plain/commit/20325a1)).
- Removed the unused `interprets_empty_strings_as_nulls` backend feature flag and the related fallback logic ([285378c](https://github.com/dropseed/plain/commit/285378c)).

### Upgrade instructions

- No changes required

## [0.34.3](https://github.com/dropseed/plain/releases/plain-models@0.34.3) (2025-06-29)

### What's changed

- Simplified log output when creating or destroying test databases during test setup. The messages now display the test database name directly and no longer reference the deprecated "alias" terminology ([a543706](https://github.com/dropseed/plain/commit/a543706)).

### Upgrade instructions

- No changes required

## [0.34.2](https://github.com/dropseed/plain/releases/plain-models@0.34.2) (2025-06-27)

### What's changed

- Fixed PostgreSQL `_nodb_cursor` fallback that could raise `TypeError: __init__() got an unexpected keyword argument 'alias'` when the maintenance database wasn't available ([3e49683](https://github.com/dropseed/plain/commit/3e49683)).
- Restored support for the `USING` clause when creating PostgreSQL indexes; custom index types such as `GIN` and `GIST` are now generated correctly again ([9d2b8fe](https://github.com/dropseed/plain/commit/9d2b8fe)).

### Upgrade instructions

- No changes required

## [0.34.1](https://github.com/dropseed/plain/releases/plain-models@0.34.1) (2025-06-23)

### What's changed

- Fixed Markdown bullet indentation in the 0.34.0 release notes so they render correctly ([2fc81de](https://github.com/dropseed/plain/commit/2fc81de)).

### Upgrade instructions

- No changes required

## [0.34.0](https://github.com/dropseed/plain/releases/plain-models@0.34.0) (2025-06-23)

### What's changed

- Switched to a single `DATABASE` setting instead of `DATABASES` and removed `DATABASE_ROUTERS`. A helper still automatically populates `DATABASE` from `DATABASE_URL` just like before ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).
- The `plain.models.db` module now exposes a `db_connection` object that lazily represents the active database connection. Previous `connections`, `router`, and `DEFAULT_DB_ALIAS` exports were removed ([d346d81](https://github.com/dropseed/plain/commit/d346d81)).

### Upgrade instructions

- Replace any `DATABASES` definition in your settings with a single `DATABASE` dict (keys are identical to the inner dict you were previously using).
- Remove any `DATABASE_ROUTERS` configuration – multiple databases are no longer supported.
- Update import sites:
    - `from plain.models import connections` → `from plain.models import db_connection`
    - `from plain.models import router` → (no longer needed; remove usage or switch to `db_connection` where appropriate)
    - `from plain.models.connections import DEFAULT_DB_ALIAS` → (constant removed; default database is implicit)
