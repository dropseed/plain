# plain-models changelog

## [0.77.1](https://github.com/dropseed/plain/releases/plain-models@0.77.1) (2026-02-13)

### What's changed

- Added migration development workflow documentation covering how to consolidate uncommitted and committed migrations ([0b30f98b5346](https://github.com/dropseed/plain/commit/0b30f98b5346))
- Added migration cleanup guidance to agent rules: consolidate before committing, use squash only for deployed migrations ([0b30f98b5346](https://github.com/dropseed/plain/commit/0b30f98b5346))

### Upgrade instructions

- No changes required.

## [0.77.0](https://github.com/dropseed/plain/releases/plain-models@0.77.0) (2026-02-13)

### What's changed

- `makemigrations --dry-run` now shows a SQL preview of the statements each migration would execute, making it easier to review schema changes before writing migration files ([c994703f9a28](https://github.com/dropseed/plain/commit/c994703f9a28))
- `makemigrations` now warns when packages have models but no `migrations/` directory, which can cause "No changes detected" confusion for new apps ([c994703f9a28](https://github.com/dropseed/plain/commit/c994703f9a28))
- Restructured README documentation: consolidated Querying section with Custom QuerySets, Typing, and Raw SQL; added N+1 avoidance and query efficiency subsections; reorganized Relationships and Constraints into clearer sections with schema design guidance ([f5d2731ebda0](https://github.com/dropseed/plain/commit/f5d2731ebda0), [8c2189a896d2](https://github.com/dropseed/plain/commit/8c2189a896d2))
- Slimmed agent rules to concise bullet reminders with `paths:` scoping for `**/models.py` files ([f5d2731ebda0](https://github.com/dropseed/plain/commit/f5d2731ebda0))

### Upgrade instructions

- No changes required.

## [0.76.5](https://github.com/dropseed/plain/releases/plain-models@0.76.5) (2026-02-12)

### What's changed

- Updated README model validation example to use `@models.register_model`, `UniqueConstraint`, and `model_options` ([9db8e0aa5d43](https://github.com/dropseed/plain/commit/9db8e0aa5d43))
- Added schema planning guidance to agent rules ([eaf55cb1b893](https://github.com/dropseed/plain/commit/eaf55cb1b893))

### Upgrade instructions

- No changes required.

## [0.76.4](https://github.com/dropseed/plain/releases/plain-models@0.76.4) (2026-02-04)

### What's changed

- Added `__all__` exports to `expressions` module for explicit public API boundaries ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Refactored internal imports to use explicit module paths instead of the `sql` namespace ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))
- Updated agent rules to use `--api` instead of `--symbols` for `plain docs` command ([e7164d3891b2](https://github.com/dropseed/plain/commit/e7164d3891b2))

### Upgrade instructions

- No changes required.

## [0.76.3](https://github.com/dropseed/plain/releases/plain-models@0.76.3) (2026-02-02)

### What's changed

- Fixed observer query summaries for SQL statements starting with parentheses (e.g., UNION queries) by stripping leading `(` before extracting the operation ([bfbcb5a256f2](https://github.com/dropseed/plain/commit/bfbcb5a256f2))
- UNION queries now display with a "UNION" suffix in query summaries for better identification ([bfbcb5a256f2](https://github.com/dropseed/plain/commit/bfbcb5a256f2))
- Agent rules now include query examples showing the `Model.query` pattern ([02e11328dbf5](https://github.com/dropseed/plain/commit/02e11328dbf5))

### Upgrade instructions

- No changes required.

## [0.76.2](https://github.com/dropseed/plain/releases/plain-models@0.76.2) (2026-01-28)

### What's changed

- Converted the `plain-models` skill to a passive `.claude/rules/` file ([512040ac51](https://github.com/dropseed/plain/commit/512040ac51))

### Upgrade instructions

- Run `plain agent install` to update your `.claude/` directory.

## [0.76.1](https://github.com/dropseed/plain/releases/plain-models@0.76.1) (2026-01-28)

### What's changed

- Added Settings section to README ([803fee1ad5](https://github.com/dropseed/plain/commit/803fee1ad5))

### Upgrade instructions

- No changes required.

## [0.76.0](https://github.com/dropseed/plain/releases/plain-models@0.76.0) (2026-01-22)

### What's changed

- Removed the `db_column` field parameter - column names are now always derived from the field name ([eed1bb6](https://github.com/dropseed/plain/commit/eed1bb6811))
- Removed the `db_collation` field parameter from `CharField` and `TextField` - use raw SQL or database-level collation settings instead ([49b362d](https://github.com/dropseed/plain/commit/49b362d3d3))
- Removed the `Collate` database function from `plain.models.functions` ([49b362d](https://github.com/dropseed/plain/commit/49b362d3d3))
- Removed the `db_comment` field parameter and `db_table_comment` model option - database comments are no longer supported ([eb5aabb](https://github.com/dropseed/plain/commit/eb5aabb5ca))
- Removed the `AlterModelTableComment` migration operation ([eb5aabb](https://github.com/dropseed/plain/commit/eb5aabb5ca))
- Added `BaseDatabaseSchemaEditor` and `StateModelsRegistry` exports from `plain.models.migrations` for use in type annotations in `RunPython` functions ([672aa88](https://github.com/dropseed/plain/commit/672aa8861a))

### Upgrade instructions

- Remove any `db_column` arguments from field definitions - the column name will always match the field's attribute name (with `_id` suffix for foreign keys)
- Remove `db_column` from all migrations
- Remove any `db_collation` arguments from `CharField` and `TextField` definitions
- Replace any usage of `Collate()` function with raw SQL queries or configure collation at the database level
- Remove any `db_comment` arguments from field definitions
- Remove `db_comment` from all migrations
- Remove any `db_table_comment` from `model_options` definitions
- Replace `AlterModelTableComment` migration operations with `RunSQL` if database comments are still needed

## [0.75.0](https://github.com/dropseed/plain/releases/plain-models@0.75.0) (2026-01-15)

### What's changed

- Added type annotations to `CursorWrapper` fetch methods (`fetchone`, `fetchmany`, `fetchall`) for better type checker support ([7635258](https://github.com/dropseed/plain/commit/7635258de0))
- Internal cleanup: removed redundant `tzinfo` class attribute from `TruncBase` ([0cb5a84](https://github.com/dropseed/plain/commit/0cb5a84718))

### Upgrade instructions

- No changes required

## [0.74.0](https://github.com/dropseed/plain/releases/plain-models@0.74.0) (2026-01-15)

### What's changed

- Internal skill configuration update - no user-facing changes ([fac8673](https://github.com/dropseed/plain/commit/fac8673436))

### Upgrade instructions

- No changes required

## [0.73.0](https://github.com/dropseed/plain/releases/plain-models@0.73.0) (2026-01-15)

### What's changed

- The `__repr__` method on models now returns `<ClassName: id>` instead of `<ClassName: str(self)>`, avoiding potential side effects from custom `__str__` implementations ([0fc4dd3](https://github.com/dropseed/plain/commit/0fc4dd345f))

### Upgrade instructions

- No changes required

## [0.72.0](https://github.com/dropseed/plain/releases/plain-models@0.72.0) (2026-01-13)

### What's changed

- Fixed `TimezoneField` deconstruct path to correctly resolve to `plain.models` instead of `plain.models.fields.timezones`, preventing migration churn when using `TimezoneField` ([03cc263](https://github.com/dropseed/plain/commit/03cc263ffa))

### Upgrade instructions

- No changes required

## [0.71.0](https://github.com/dropseed/plain/releases/plain-models@0.71.0) (2026-01-13)

### What's changed

- `TimeZoneField` choices are no longer serialized in migrations, preventing spurious migration diffs when timezone data differs between machines ([0ede3aae](https://github.com/dropseed/plain/commit/0ede3aae5d))
- `TimeZoneField` no longer accepts custom choices - the field's purpose is to provide the canonical timezone list ([0ede3aae](https://github.com/dropseed/plain/commit/0ede3aae5d))
- Simplified `plain migrate` output - package name is only shown when explicitly targeting a specific package ([006efae9](https://github.com/dropseed/plain/commit/006efae92d))
- Field ordering is now explicit (primary key first, then alphabetically by name) instead of using an internal creation counter ([3ffa44bd](https://github.com/dropseed/plain/commit/3ffa44bdcb))

### Upgrade instructions

- If you have existing migrations that contain `TimeZoneField` with serialized `choices`, you can safely remove the `choices` parameter from those migrations as they are now computed dynamically
- If you were passing custom `choices` to `TimeZoneField`, this is no longer supported - use a regular `CharField` with choices instead

## [0.70.0](https://github.com/dropseed/plain/releases/plain-models@0.70.0) (2025-12-26)

### What's changed

- Added `TimeZoneField` for storing timezone information - stores timezone names as strings in the database but provides `zoneinfo.ZoneInfo` objects when accessed, similar to how `DateField` works with `datetime.date` ([b533189](https://github.com/dropseed/plain/commit/b533189576))
- Documentation improvements listing all available field types in the README ([11837ad](https://github.com/dropseed/plain/commit/11837ad2f2))

### Upgrade instructions

- No changes required

## [0.69.1](https://github.com/dropseed/plain/releases/plain-models@0.69.1) (2025-12-22)

### What's changed

- Internal type annotation improvements for better type checker compatibility ([539a706](https://github.com/dropseed/plain/commit/539a706760), [5c0e403](https://github.com/dropseed/plain/commit/5c0e403863))

### Upgrade instructions

- No changes required

## [0.69.0](https://github.com/dropseed/plain/releases/plain-models@0.69.0) (2025-12-12)

### What's changed

- The `queryset.all()` method now preserves the prefetch cache, fixing an issue where accessing prefetched related objects through `.all()` would trigger additional database queries instead of using the cached results ([8b899a8](https://github.com/dropseed/plain/commit/8b899a807a))

### Upgrade instructions

- No changes required

## [0.68.0](https://github.com/dropseed/plain/releases/plain-models@0.68.0) (2025-12-09)

### What's changed

- Database backups now store git metadata (branch and commit) and the `plain db backups list` command displays this information along with source and size in a table format ([287fa89f](https://github.com/dropseed/plain/commit/287fa89fb1))
- Added `--branch` option to `plain db backups list` to filter backups by git branch ([287fa89f](https://github.com/dropseed/plain/commit/287fa89fb1))
- `ReverseForeignKey` and `ReverseManyToMany` now support an optional second type parameter for custom QuerySet types, enabling type checkers to recognize custom QuerySet methods on reverse relations ([487c6195](https://github.com/dropseed/plain/commit/487c6195bf))
- Internal cleanup: removed legacy generic foreign key related code ([c9ca1b67](https://github.com/dropseed/plain/commit/c9ca1b670a))

### Upgrade instructions

- To get type checking for custom QuerySet methods on reverse relations, you can optionally add a second type parameter: `books: types.ReverseForeignKey[Book, BookQuerySet] = types.ReverseForeignKey(to="Book", field="author")`. This is optional and existing code without the second parameter continues to work.

## [0.67.0](https://github.com/dropseed/plain/releases/plain-models@0.67.0) (2025-12-05)

### What's changed

- Simplified Query/Compiler architecture by moving compiler selection from Query classes to DatabaseOperations ([1d1ae5a6](https://github.com/dropseed/plain/commit/1d1ae5a61f))
- The `raw()` method now accepts any `Sequence` for params (e.g., lists) instead of requiring tuples ([1d1ae5a6](https://github.com/dropseed/plain/commit/1d1ae5a61f))
- Internal type annotation improvements across database backends and SQL compiler modules ([bc02184d](https://github.com/dropseed/plain/commit/bc02184de7), [e068dcf2](https://github.com/dropseed/plain/commit/e068dcf201), [33fa09d6](https://github.com/dropseed/plain/commit/33fa09d66f))

### Upgrade instructions

- No changes required

## [0.66.0](https://github.com/dropseed/plain/releases/plain-models@0.66.0) (2025-12-05)

### What's changed

- Removed `union()`, `intersection()`, and `difference()` combinator methods from QuerySet - use raw SQL for set operations instead ([0bae6abd](https://github.com/dropseed/plain/commit/0bae6abd94))
- Removed `dates()` and `datetimes()` methods from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Removed `in_bulk()` method from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Removed `contains()` method from QuerySet ([62ba81a6](https://github.com/dropseed/plain/commit/62ba81a627))
- Internal cleanup: removed unused database backend feature flags and operations (`autoinc_sql`, `allows_group_by_selected_pks_on_model`, `connection_persists_old_columns`, `implied_column_null`, `for_update_after_from`, `select_for_update_of_column`, `modify_insert_params`) ([defe5015](https://github.com/dropseed/plain/commit/defe5015e6), [7e62b635](https://github.com/dropseed/plain/commit/7e62b635ba), [30073da1](https://github.com/dropseed/plain/commit/30073da128))

### Upgrade instructions

- Replace any usage of `queryset.union(other_qs)`, `queryset.intersection(other_qs)`, or `queryset.difference(other_qs)` with raw SQL queries using `Model.query.raw()` or database cursors
- Replace `queryset.dates(field, kind)` with equivalent annotate/values_list queries using `Trunc` and `DateField`
- Replace `queryset.datetimes(field, kind)` with equivalent annotate/values_list queries using `Trunc` and `DateTimeField`
- Replace `queryset.in_bulk(id_list)` with a dictionary comprehension like `{obj.id: obj for obj in queryset.filter(id__in=id_list)}`
- Replace `queryset.contains(obj)` with `queryset.filter(id=obj.id).exists()`

## [0.65.1](https://github.com/dropseed/plain/releases/plain-models@0.65.1) (2025-12-04)

### What's changed

- Fixed type annotations for `get_rhs_op` method in lookup classes to accept `str | list[str]` parameter, resolving type checker errors when using `Range` and other lookups that return list-based RHS values ([7030cd0](https://github.com/dropseed/plain/commit/7030cd0ee0))

### Upgrade instructions

- No changes required

## [0.65.0](https://github.com/dropseed/plain/releases/plain-models@0.65.0) (2025-12-04)

### What's changed

- Improved type annotations for `ReverseForeignKey` and `ReverseManyToMany` descriptors - they are now proper generic descriptor classes with `__get__` overloads, providing better type inference when accessed on class vs instance ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))
- Internal type annotation improvements across aggregates, expressions, database backends, and SQL compiler modules ([ac1eeb0](https://github.com/dropseed/plain/commit/ac1eeb0ea0))

### Upgrade instructions

- No changes required

## [0.64.0](https://github.com/dropseed/plain/releases/plain-models@0.64.0) (2025-11-24)

### What's changed

- `bulk_create()` and `bulk_update()` now accept any `Sequence` type (e.g., tuples, generators) instead of requiring a `list` ([6c7469f](https://github.com/dropseed/plain/commit/6c7469f92a))

### Upgrade instructions

- No changes required

## [0.63.1](https://github.com/dropseed/plain/releases/plain-models@0.63.1) (2025-11-21)

### What's changed

- Fixed `ManyToManyField` preflight checks that could fail when the intermediate model contained non-related fields (e.g., `CharField`, `IntegerField`) by properly filtering to only check `RelatedField` instances when counting foreign keys ([4a3fe5d](https://github.com/dropseed/plain/commit/4a3fe5d530))

### Upgrade instructions

- No changes required

## [0.63.0](https://github.com/dropseed/plain/releases/plain-models@0.63.0) (2025-11-21)

### What's changed

- `ForeignKey` has been renamed to `ForeignKeyField` for consistency with other field naming conventions ([8010204](https://github.com/dropseed/plain/commit/8010204b36))
- Improved type annotations for `ManyToManyField` - now returns `ManyToManyManager[T]` instead of `Any` for better IDE support ([4536097](https://github.com/dropseed/plain/commit/4536097be1))
- Related managers (`ReverseForeignKeyManager` and `ManyToManyManager`) are now generic classes with proper type parameters for improved type checking ([3f61b6e](https://github.com/dropseed/plain/commit/3f61b6e51f))
- Added `ManyToManyManager` and `ReverseForeignKeyManager` exports to `plain.models.types` for use in type annotations ([4536097](https://github.com/dropseed/plain/commit/4536097be1))

### Upgrade instructions

- Replace all usage of `models.ForeignKey` with `models.ForeignKeyField` (e.g., `category = models.ForeignKey("Category", on_delete=models.CASCADE)` becomes `category = models.ForeignKeyField("Category", on_delete=models.CASCADE)`)
- Replace all usage of `types.ForeignKey` with `types.ForeignKeyField` in typed model definitions
- Update migrations to use `ForeignKeyField` instead of `ForeignKey`

## [0.62.1](https://github.com/dropseed/plain/releases/plain-models@0.62.1) (2025-11-20)

### What's changed

- Fixed a bug where non-related fields could cause errors in migrations and schema operations by incorrectly assuming all fields have a `remote_field` attribute ([60b1bcc](https://github.com/dropseed/plain/commit/60b1bcc1c5))

### Upgrade instructions

- No changes required

## [0.62.0](https://github.com/dropseed/plain/releases/plain-models@0.62.0) (2025-11-20)

### What's changed

- The `named` parameter has been removed from `QuerySet.values_list()` - named tuples are no longer supported for values lists ([0e39711](https://github.com/dropseed/plain/commit/0e397114c2))
- Internal method `get_extra_restriction()` has been removed from related fields and query data structures ([6157bd9](https://github.com/dropseed/plain/commit/6157bd90385137faf2cafbbd423a99326eedcd3b))
- Internal helper function `get_model_meta()` has been removed in favor of direct attribute access ([cb5a50e](https://github.com/dropseed/plain/commit/cb5a50ef1a0c5af61b97b96459bb14ed85df6f7f))
- Extensive type annotation improvements across the entire package, including database backends, query compilers, fields, migrations, and SQL modules ([a43145e](https://github.com/dropseed/plain/commit/a43145e69732a792b376e6548c6aac384df0ce28))
- Added `isinstance` checks for related fields and improved type narrowing throughout the codebase ([5b4bdf4](https://github.com/dropseed/plain/commit/5b4bdf47e74964780300e20c5fabfce68fa424c7))
- Improved type annotations for `Options.get_fields()` and related meta methods with more specific return types ([2c26f86](https://github.com/dropseed/plain/commit/2c26f86573df0cef473153d6224abdb99082e893))

### Upgrade instructions

- Remove any usage of the `named=True` parameter in `values_list()` calls - if you need named access to query results, use `.values()` which returns dictionaries instead

## [0.61.1](https://github.com/dropseed/plain/releases/plain-models@0.61.1) (2025-11-17)

### What's changed

- The `@dataclass_transform` decorator has been removed from `ModelBase` to avoid type checker issues ([e0dbedb](https://github.com/dropseed/plain/commit/e0dbedb73f))
- Documentation and examples no longer suggest using `ClassVar` for QuerySet type annotations - the simpler `query: models.QuerySet[Model] = models.QuerySet()` pattern is now recommended ([1c624ff](https://github.com/dropseed/plain/commit/1c624ff29e), [99aecbc](https://github.com/dropseed/plain/commit/99aecbc17e))

### Upgrade instructions

- If you were using `ClassVar` annotations for the `query` attribute, you can optionally remove the `ClassVar` wrapper and the `from typing import ClassVar` import. Both patterns work, but the simpler version without `ClassVar` is now recommended.

## [0.61.0](https://github.com/dropseed/plain/releases/plain-models@0.61.0) (2025-11-14)

### What's changed

- The `related_name` parameter has been removed from `ForeignKey` and `ManyToManyField` - reverse relationships are now declared explicitly using `ReverseForeignKey` and `ReverseManyToMany` descriptors on the related model ([a4b630969d](https://github.com/dropseed/plain/commit/a4b630969d))
- Added `ReverseForeignKey` and `ReverseManyToMany` descriptor classes to `plain.models.types` for declaring reverse relationships with full type support ([a4b630969d](https://github.com/dropseed/plain/commit/a4b630969d))
- The new reverse descriptors are exported from `plain.models` for easy access ([97fa112975](https://github.com/dropseed/plain/commit/97fa112975))
- Renamed internal references from `ManyToOne` to `ForeignKey` for consistency ([93c30f9caf](https://github.com/dropseed/plain/commit/93c30f9caf))
- Fixed a preflight check bug related to reverse relationships ([9191ae6e4b](https://github.com/dropseed/plain/commit/9191ae6e4b))
- Added comprehensive documentation for reverse relationships in the README ([5abf330e06](https://github.com/dropseed/plain/commit/5abf330e06))

### Upgrade instructions

- Remove all `related_name` parameters from `ForeignKey` and `ManyToManyField` definitions
- Remove `related_name` from all migrations
- On the related model, add explicit reverse relationship descriptors using `ReverseForeignKey` or `ReverseManyToMany` from `plain.models.types`:
    - For the reverse side of a `ForeignKey`, use: `children: types.ReverseForeignKey[Child] = types.ReverseForeignKey(to="Child", field="parent")`
    - For the reverse side of a `ManyToManyField`, use: `cars: types.ReverseManyToMany[Car] = types.ReverseManyToMany(to="Car", field="features")`
- Remove any `TYPE_CHECKING` blocks that were used to declare reverse relationship types - the new descriptors provide full type support without these hacks
- The `to` parameter accepts either a string (model name) or the model class itself
- The `field` parameter should be the name of the forward field on the related model

## [0.60.0](https://github.com/dropseed/plain/releases/plain-models@0.60.0) (2025-11-13)

### What's changed

- Type annotations for QuerySets using `ClassVar` to improve type checking when accessing `Model.query` ([c3b00a6](https://github.com/dropseed/plain/commit/c3b00a693c))
- The `id` field on the Model base class now uses a type annotation (`id: int = types.PrimaryKeyField()`) for better type checking ([9febc80](https://github.com/dropseed/plain/commit/9febc801f4))
- Replaced wildcard imports (`import *`) with explicit imports in internal modules for better code clarity ([eff36f3](https://github.com/dropseed/plain/commit/eff36f31e8))

### Upgrade instructions

- Optionally (but recommended) add `ClassVar` type annotations to custom QuerySets on your models using `query: ClassVar[models.QuerySet[YourModel]] = models.QuerySet()` for improved type checking and IDE autocomplete

## [0.59.1](https://github.com/dropseed/plain/releases/plain-models@0.59.1) (2025-11-13)

### What's changed

- Added documentation for typed field definitions in the README, showing examples of using `plain.models.types` with type annotations ([f95d32d](https://github.com/dropseed/plain/commit/f95d32df5a))

### Upgrade instructions

- Optionally (but recommended) move to typed model field definitions by using `name: str = types.CharField(...)` instead of `name = models.CharField(...)`. Types can be imported with `from plain.models import types`.

## [0.59.0](https://github.com/dropseed/plain/releases/plain-models@0.59.0) (2025-11-13)

### What's changed

- Added a new `plain.models.types` module with type stub support (.pyi) for improved IDE and type checker experience when defining models ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc75a))
- Added `@dataclass_transform` decorator to `ModelBase` to enable better type checking for model field definitions ([c8f40fc](https://github.com/dropseed/plain/commit/c8f40fc75a))

### Upgrade instructions

- No changes required

## [0.58.0](https://github.com/dropseed/plain/releases/plain-models@0.58.0) (2025-11-12)

### What's changed

- Internal base classes have been converted to use Python's ABC (Abstract Base Class) module with `@abstractmethod` decorators, improving type checking and making the codebase more maintainable ([b1f40759](https://github.com/dropseed/plain/commit/b1f40759eb), [7146cabc](https://github.com/dropseed/plain/commit/7146cabc42), [74f9a171](https://github.com/dropseed/plain/commit/74f9a1717a), [b647d156](https://github.com/dropseed/plain/commit/b647d156ce), [6f3e35d9](https://github.com/dropseed/plain/commit/6f3e35d9b0), [95620673](https://github.com/dropseed/plain/commit/95620673d9), [7ff5e98c](https://github.com/dropseed/plain/commit/7ff5e98c6f), [78323300](https://github.com/dropseed/plain/commit/78323300df), [df82434d](https://github.com/dropseed/plain/commit/df82434d50), [16350d98](https://github.com/dropseed/plain/commit/16350d98b1), [066eaa4b](https://github.com/dropseed/plain/commit/066eaa4bd7), [60fabefa](https://github.com/dropseed/plain/commit/60fabefa77), [9f822ccc](https://github.com/dropseed/plain/commit/9f822cccc8), [6b31752c](https://github.com/dropseed/plain/commit/6b31752c95))
- Type annotations have been improved across database backends, query compilers, and migrations for better IDE support ([f4dbcefa](https://github.com/dropseed/plain/commit/f4dbcefa92), [dc182c2e](https://github.com/dropseed/plain/commit/dc182c2e51))

### Upgrade instructions

- No changes required

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
