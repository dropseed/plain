from __future__ import annotations

import inspect
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from plain.models.db import db_connection
from plain.models.registry import ModelsRegistry, models_registry
from plain.packages import packages_registry
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check("models.database_backends")
class CheckDatabaseBackends(PreflightCheck):
    """Validates database backend configuration when plain.models is available."""

    def run(self) -> list[PreflightResult]:
        return db_connection.validation.preflight()


@register_check("models.all_models")
class CheckAllModels(PreflightCheck):
    """Validates all model definitions for common issues."""

    def run(self) -> list[PreflightResult]:
        db_table_models = defaultdict(list)
        indexes = defaultdict(list)
        constraints = defaultdict(list)
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
                        id="models.preflight_method_overridden",
                    )
                )
            else:
                errors.extend(model.preflight())
            for model_index in model.model_options.indexes:
                indexes[model_index.name].append(model.model_options.label)
            for model_constraint in model.model_options.constraints:
                constraints[model_constraint.name].append(model.model_options.label)
        for db_table, model_labels in db_table_models.items():
            if len(model_labels) != 1:
                model_labels_str = ", ".join(model_labels)
                errors.append(
                    PreflightResult(
                        fix=f"db_table '{db_table}' is used by multiple models: {model_labels_str}.",
                        obj=db_table,
                        id="models.duplicate_db_table",
                    )
                )
        for index_name, model_labels in indexes.items():
            if len(model_labels) > 1:
                model_labels = set(model_labels)
                errors.append(
                    PreflightResult(
                        fix="index name '{}' is not unique {} {}.".format(
                            index_name,
                            "for model" if len(model_labels) == 1 else "among models:",
                            ", ".join(sorted(model_labels)),
                        ),
                        id="models.index_name_not_unique_single"
                        if len(model_labels) == 1
                        else "models.index_name_not_unique_multiple",
                    ),
                )
        for constraint_name, model_labels in constraints.items():
            if len(model_labels) > 1:
                model_labels = set(model_labels)
                errors.append(
                    PreflightResult(
                        fix="constraint name '{}' is not unique {} {}.".format(
                            constraint_name,
                            "for model" if len(model_labels) == 1 else "among models:",
                            ", ".join(sorted(model_labels)),
                        ),
                        id="models.constraint_name_not_unique_single"
                        if len(model_labels) == 1
                        else "models.constraint_name_not_unique_multiple",
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
            id="models.lazy_reference_resolution_failed",
        )

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy = {
        ("plain.models.fields.related", "resolve_related_class"): field_error,
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
        key=lambda error: error.message,
    )


@register_check("models.lazy_references")
class CheckLazyReferences(PreflightCheck):
    """Ensures all lazy (string) model references have been resolved."""

    def run(self) -> list[PreflightResult]:
        return _check_lazy_references(models_registry, packages_registry)


@register_check("models.database_tables")
class CheckDatabaseTables(PreflightCheck):
    """Checks for unknown tables in the database when plain.models is available."""

    def run(self) -> list[PreflightResult]:
        errors = []

        db_tables = db_connection.introspection.table_names()
        model_tables = db_connection.introspection.plain_table_names()
        unknown_tables = set(db_tables) - set(model_tables)
        unknown_tables.discard("plainmigrations")  # Know this could be there
        if unknown_tables:
            table_names = ", ".join(unknown_tables)
            specific_fix = (
                f'echo "DROP TABLE IF EXISTS {unknown_tables.pop()}" | plain db shell'
            )
            errors.append(
                PreflightResult(
                    fix=f"Unknown tables in default database: {table_names}. "
                    "Tables may be from packages/models that have been uninstalled. "
                    "Make sure you have a backup and delete the tables manually "
                    f"(ex. `{specific_fix}`).",
                    id="models.unknown_database_tables",
                    warning=True,
                )
            )

        return errors


@register_check("models.prunable_migrations")
class CheckPrunableMigrations(PreflightCheck):
    """Warns about stale migration records in the database."""

    def run(self) -> list[PreflightResult]:
        # Import here to avoid circular import issues
        from plain.models.migrations.loader import MigrationLoader
        from plain.models.migrations.recorder import MigrationRecorder

        errors = []

        # Load migrations from disk and database
        loader = MigrationLoader(db_connection, ignore_no_migrations=True)
        recorder = MigrationRecorder(db_connection)
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
                id="models.prunable_migrations",
                warning=True,
            )
        )

        return errors
