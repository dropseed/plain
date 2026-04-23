from __future__ import annotations

from .types import Source, TableOwner


def build_table_owners() -> dict[str, TableOwner]:
    """Map table names to their owning package, source, and model class."""
    import inspect

    from plain.packages import packages_registry
    from plain.postgres import models_registry

    def _source_file(cls: type) -> str:
        try:
            path = inspect.getsourcefile(cls)
        except (TypeError, OSError):
            return ""
        return path or ""

    owners: dict[str, TableOwner] = {}
    for package_config in packages_registry.get_package_configs():
        source = "app" if package_config.name.startswith("app.") else "package"
        for model in models_registry.get_models(
            package_label=package_config.package_label
        ):
            owners[model.model_options.db_table] = TableOwner(
                package_label=package_config.package_label,
                source=source,
                model_class=model.__name__,
                model_file=_source_file(model),
            )
            for field in model._model_meta.local_many_to_many:
                m2m_table = field.m2m_db_table()
                if m2m_table in owners:
                    # Explicit "through" model already registered with its class.
                    continue
                owners[m2m_table] = TableOwner(
                    package_label=package_config.package_label,
                    source=source,
                    model_class="",  # auto-generated join table, no class
                    model_file="",
                )
    return owners


def _table_info(
    table_name: str, table_owners: dict[str, TableOwner]
) -> tuple[Source, str, str, str]:
    """Return (source, package, model_class, model_file) for a table name.

    model_class and model_file are populated only for app-owned tables so
    findings can suggest exact model edits. Package tables have a model class
    but the user can't edit it from their app.
    """
    owner = table_owners.get(table_name)
    if not owner:
        return "", "", "", ""
    if owner["source"] == "app":
        return (
            owner["source"],
            owner["package_label"],
            owner["model_class"],
            owner["model_file"],
        )
    return owner["source"], owner["package_label"], "", ""
