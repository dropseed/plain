from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from plain.packages import packages_registry
from plain.postgres.constraints import UniqueConstraint
from plain.postgres.db import get_connection
from plain.postgres.fields.related import ForeignKeyField
from plain.postgres.migrations.recorder import MIGRATION_TABLE_NAME
from plain.postgres.registry import ModelsRegistry, models_registry
from plain.preflight import PreflightCheck, PreflightResult, register_check


def _get_app_models() -> list[Any]:
    """Return models from the user's app packages only (not framework/third-party)."""
    app_models = []
    for package_config in packages_registry.get_package_configs():
        if package_config.name.startswith("app."):
            app_models.extend(
                models_registry.get_models(package_label=package_config.package_label)
            )
    return app_models


def _collect_model_indexes(model: Any) -> list[tuple[str, list[str], bool]]:
    """Collect all index field-lists for a model as (name, fields, is_unique) tuples."""
    all_indexes: list[tuple[str, list[str], bool]] = []

    for index in model.model_options.indexes:
        if index.fields:
            fields = [f.lstrip("-") for f in index.fields]
            all_indexes.append((index.name, fields, False))

    for constraint in model.model_options.constraints:
        if isinstance(constraint, UniqueConstraint) and constraint.fields:
            all_indexes.append((constraint.name, list(constraint.fields), True))

    return all_indexes


@register_check("postgres.all_models")
class CheckAllModels(PreflightCheck):
    """Validates all model definitions for common issues."""

    def run(self) -> list[PreflightResult]:
        db_table_models = defaultdict(list)
        # Indexes and constraints share the same Postgres namespace,
        # so track them together to catch cross-type collisions.
        relation_names = defaultdict(list)
        errors = []
        models = models_registry.get_models()
        for model in models:
            db_table_models[model.model_options.db_table].append(
                model.model_options.label
            )
            if not inspect.ismethod(model.preflight):
                errors.append(
                    PreflightResult(
                        fix=f"The '{model.__name__}.preflight()' class method is currently overridden by {model.preflight!r}.",
                        obj=model,
                        id="postgres.preflight_method_overridden",
                    )
                )
            else:
                errors.extend(model.preflight())
            for model_index in model.model_options.indexes:
                relation_names[model_index.name].append(model.model_options.label)
            for model_constraint in model.model_options.constraints:
                relation_names[model_constraint.name].append(model.model_options.label)
        for db_table, model_labels in db_table_models.items():
            if len(model_labels) != 1:
                model_labels_str = ", ".join(model_labels)
                errors.append(
                    PreflightResult(
                        fix=f"db_table '{db_table}' is used by multiple models: {model_labels_str}.",
                        obj=db_table,
                        id="postgres.duplicate_db_table",
                    )
                )
        for relation_name, model_labels in relation_names.items():
            if len(model_labels) > 1:
                unique_models = set(model_labels)
                single_model = len(unique_models) == 1
                errors.append(
                    PreflightResult(
                        fix="index/constraint name '{}' is not unique {} {}.".format(
                            relation_name,
                            "for model" if single_model else "among models:",
                            ", ".join(sorted(unique_models)),
                        ),
                        id="postgres.relation_name_not_unique_single"
                        if single_model
                        else "postgres.relation_name_not_unique_multiple",
                    ),
                )
        return errors


def _check_lazy_references(
    models_registry: ModelsRegistry, packages_registry: Any
) -> list[PreflightResult]:
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Lazy references are used in various places throughout Plain, primarily in
    related fields and model signals. Identify those common cases and provide
    more helpful error messages for them.
    """
    pending_models = set(models_registry._pending_operations)

    # Short circuit if there aren't any errors.
    if not pending_models:
        return []

    def extract_operation(
        obj: Any,
    ) -> tuple[Callable[..., Any], list[Any], dict[str, Any]]:
        """
        Take a callable found in Packages._pending_operations and identify the
        original callable passed to Packages.lazy_model_operation(). If that
        callable was a partial, return the inner, non-partial function and
        any arguments and keyword arguments that were supplied with it.

        obj is a callback defined locally in Packages.lazy_model_operation() and
        annotated there with a `func` attribute so as to imitate a partial.
        """
        operation, args, keywords = obj, [], {}
        while hasattr(operation, "func"):
            args.extend(getattr(operation, "args", []))
            keywords.update(getattr(operation, "keywords", {}))
            operation = operation.func
        return operation, args, keywords

    def app_model_error(model_key: tuple[str, str]) -> str:
        try:
            packages_registry.get_package_config(model_key[0])
            model_error = "app '{}' doesn't provide model '{}'".format(*model_key)
        except LookupError:
            model_error = f"app '{model_key[0]}' isn't installed"
        return model_error

    # Here are several functions which return CheckMessage instances for the
    # most common usages of lazy operations throughout Plain. These functions
    # take the model that was being waited on as an (package_label, modelname)
    # pair, the original lazy function, and its positional and keyword args as
    # determined by extract_operation().

    def field_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult:
        error_msg = (
            "The field %(field)s was declared with a lazy reference "
            "to '%(model)s', but %(model_error)s."
        )
        params = {
            "model": ".".join(model_key),
            "field": keywords["field"],
            "model_error": app_model_error(model_key),
        }
        return PreflightResult(
            fix=error_msg % params,
            obj=keywords["field"],
            id="fields.lazy_reference_not_resolvable",
        )

    def default_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult:
        error_msg = (
            "%(op)s contains a lazy reference to %(model)s, but %(model_error)s."
        )
        params = {
            "op": func,
            "model": ".".join(model_key),
            "model_error": app_model_error(model_key),
        }
        return PreflightResult(
            fix=error_msg % params,
            obj=func,
            id="postgres.lazy_reference_resolution_failed",
        )

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy = {
        ("plain.postgres.fields.related", "resolve_related_class"): field_error,
    }

    def build_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult | None:
        key = (func.__module__, func.__name__)  # type: ignore[attr-defined]
        error_fn = known_lazy.get(key, default_error)
        return error_fn(model_key, func, args, keywords) if error_fn else None

    return sorted(
        filter(
            None,
            (
                build_error(model_key, *extract_operation(func))
                for model_key in pending_models
                for func in models_registry._pending_operations[model_key]
            ),
        ),
        key=lambda error: error.fix,
    )


@register_check("postgres.lazy_references")
class CheckLazyReferences(PreflightCheck):
    """Ensures all lazy (string) model references have been resolved."""

    def run(self) -> list[PreflightResult]:
        return _check_lazy_references(models_registry, packages_registry)


@register_check("postgres.postgres_version")
class CheckPostgresVersion(PreflightCheck):
    """Checks that the PostgreSQL server meets the minimum version requirement."""

    MINIMUM_VERSION = 16

    def run(self) -> list[PreflightResult]:
        conn = get_connection()
        major, minor = divmod(conn.pg_version, 10000)
        if major < self.MINIMUM_VERSION:
            return [
                PreflightResult(
                    fix=f"PostgreSQL {self.MINIMUM_VERSION} or later is required (found {major}.{minor}).",
                    id="postgres.postgres_version_too_old",
                )
            ]
        return []


@register_check("postgres.database_tables")
class CheckDatabaseTables(PreflightCheck):
    """Checks for unknown tables in the database when plain.postgres is available."""

    def run(self) -> list[PreflightResult]:
        conn = get_connection()
        unknown_tables = (
            set(conn.table_names())
            - set(conn.plain_table_names())
            - {MIGRATION_TABLE_NAME}
        )

        if not unknown_tables:
            return []

        table_names = ", ".join(sorted(unknown_tables))
        return [
            PreflightResult(
                fix=f"Unknown tables in default database: {table_names}. "
                "Tables may be from packages/models that have been uninstalled. "
                "Make sure you have a backup, then run `plain postgres drop-unknown-tables` to remove them.",
                id="postgres.unknown_database_tables",
                warning=True,
            )
        ]


@register_check("postgres.prunable_migrations")
class CheckPrunableMigrations(PreflightCheck):
    """Warns about stale migration records in the database."""

    def run(self) -> list[PreflightResult]:
        # Import here to avoid circular import issues
        from plain.postgres.migrations.loader import MigrationLoader
        from plain.postgres.migrations.recorder import MigrationRecorder

        errors = []

        # Load migrations from disk and database
        conn = get_connection()
        loader = MigrationLoader(conn, ignore_no_migrations=True)
        recorder = MigrationRecorder(conn)
        recorded_migrations = recorder.applied_migrations()

        # disk_migrations should not be None after MigrationLoader initialization,
        # but check to satisfy type checker
        if loader.disk_migrations is None:
            return errors

        # Find all prunable migrations (recorded but not on disk)
        all_prunable = [
            migration
            for migration in recorded_migrations
            if migration not in loader.disk_migrations
        ]

        if not all_prunable:
            return errors

        # Separate into existing packages vs orphaned packages
        existing_packages = set(loader.migrated_packages)
        prunable_existing: list[tuple[str, str]] = []
        prunable_orphaned: list[tuple[str, str]] = []

        for migration in all_prunable:
            package, name = migration
            if package in existing_packages:
                prunable_existing.append(migration)
            else:
                prunable_orphaned.append(migration)

        # Build the warning message
        total_count = len(all_prunable)
        message_parts = [
            f"Found {total_count} stale migration record{'s' if total_count != 1 else ''} in the database."
        ]

        if prunable_existing:
            existing_list = ", ".join(
                f"{pkg}.{name}" for pkg, name in prunable_existing[:3]
            )
            if len(prunable_existing) > 3:
                existing_list += f" (and {len(prunable_existing) - 3} more)"
            message_parts.append(f"From existing packages: {existing_list}.")

        if prunable_orphaned:
            orphaned_list = ", ".join(
                f"{pkg}.{name}" for pkg, name in prunable_orphaned[:3]
            )
            if len(prunable_orphaned) > 3:
                orphaned_list += f" (and {len(prunable_orphaned) - 3} more)"
            message_parts.append(f"From removed packages: {orphaned_list}.")

        message_parts.append("Run 'plain migrations prune' to review and remove them.")

        errors.append(
            PreflightResult(
                fix=" ".join(message_parts),
                id="postgres.prunable_migrations",
                warning=True,
            )
        )

        return errors


@register_check("postgres.missing_fk_indexes")
class CheckMissingFKIndexes(PreflightCheck):
    """Warns about foreign key fields without index coverage."""

    def run(self) -> list[PreflightResult]:
        results = []

        for model in _get_app_models():
            # Leading field of each index/constraint covers FK lookups
            covered_fields = {
                fields[0] for _, fields, _ in _collect_model_indexes(model)
            }

            for field in model._model_meta.local_fields:
                if (
                    isinstance(field, ForeignKeyField)
                    and not field.primary_key
                    and field.name not in covered_fields
                ):
                    results.append(
                        PreflightResult(
                            fix=f"Foreign key '{field.name}' has no index coverage. "
                            f"Add an Index on [\"{field.name}\"] or a constraint with '{field.name}' as the first field.",
                            obj=f"{model.model_options.label}.{field.name}",
                            id="postgres.missing_fk_index",
                            warning=True,
                        )
                    )

        return results


@register_check("postgres.duplicate_indexes")
class CheckDuplicateIndexes(PreflightCheck):
    """Warns about indexes that are prefix-redundant with other indexes or constraints."""

    def run(self) -> list[PreflightResult]:
        results = []

        for model in _get_app_models():
            all_indexes = _collect_model_indexes(model)

            flagged: set[str] = set()
            for i, idx_a in enumerate(all_indexes):
                for idx_b in all_indexes[i + 1 :]:
                    for shorter, longer in [(idx_a, idx_b), (idx_b, idx_a)]:
                        s_name, s_fields, s_unique = shorter
                        l_name, l_fields, _ = longer
                        if (
                            s_name not in flagged
                            and len(s_fields) < len(l_fields)
                            and l_fields[: len(s_fields)] == s_fields
                            and not s_unique
                        ):
                            results.append(
                                PreflightResult(
                                    fix=f"Index '{s_name}' on [{', '.join(s_fields)}] "
                                    f"is redundant with '{l_name}' on [{', '.join(l_fields)}]. "
                                    f"The longer index covers the same queries.",
                                    obj=model.model_options.label,
                                    id="postgres.duplicate_index",
                                    warning=True,
                                )
                            )
                            flagged.add(s_name)

        return results
