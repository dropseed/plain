from __future__ import annotations

from .types import TableOwner


def build_table_owners() -> dict[str, TableOwner]:
    """Map table names to their owning package and source (app vs dependency)."""
    from plain.packages import packages_registry
    from plain.postgres import models_registry

    owners: dict[str, TableOwner] = {}
    for package_config in packages_registry.get_package_configs():
        source = "app" if package_config.name.startswith("app.") else "package"
        for model in models_registry.get_models(
            package_label=package_config.package_label
        ):
            owners[model.model_options.db_table] = TableOwner(
                package_label=package_config.package_label,
                source=source,
            )
            for field in model._model_meta.local_many_to_many:
                owners[field.m2m_db_table()] = TableOwner(
                    package_label=package_config.package_label,
                    source=source,
                )
    return owners


def _table_source(
    table_name: str, table_owners: dict[str, TableOwner]
) -> tuple[str, str]:
    """Return (source, package) for a table name."""
    owner = table_owners.get(table_name)
    if owner:
        return owner["source"], owner["package_label"]
    return "", ""
