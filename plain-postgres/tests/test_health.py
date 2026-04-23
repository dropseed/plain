"""Tests for plain.postgres.introspection.health."""

from __future__ import annotations

import pytest

from plain.postgres.introspection import build_table_owners


@pytest.mark.usefixtures("_unblock_cursor", "db")
class TestBuildTableOwners:
    def test_populates_model_class_for_app_models(self) -> None:
        owners = build_table_owners()
        assert owners, "build_table_owners returned empty dict"

        app_entries = [o for o in owners.values() if o["source"] == "app"]
        assert app_entries, "no app-owned tables found in test fixtures"

        for owner in app_entries:
            assert "model_class" in owner, "TableOwner missing model_class key"
            # Primary model tables have class names and source files; m2m
            # join tables have neither.
            if owner["model_class"]:
                assert owner["model_file"].endswith(".py"), (
                    f"model_class={owner['model_class']} present but "
                    f"model_file={owner['model_file']!r} doesn't look like a .py file"
                )

    def test_model_class_matches_model_name(self) -> None:
        """Confirm the stored class name equals the actual model __name__."""
        import inspect

        from plain.packages import packages_registry
        from plain.postgres import models_registry

        owners = build_table_owners()
        all_models = []
        for config in packages_registry.get_package_configs():
            all_models.extend(
                models_registry.get_models(package_label=config.package_label)
            )

        for model in all_models:
            owner = owners.get(model.model_options.db_table)
            if owner and owner["source"] == "app":
                assert owner["model_class"] == model.__name__
                assert owner["model_file"] == inspect.getsourcefile(model)
