from __future__ import annotations

from app.examples.models import Car
from conftest_convergence import (
    create_invalid_index,
    execute,
    index_exists,
    index_is_valid,
)

from plain.postgres import Index, get_connection
from plain.postgres.convergence import (
    CreateIndexFix,
    DropIndexFix,
    RebuildIndexFix,
    RenameIndexFix,
    plan_model_convergence,
)


class TestDetectIndexFixes:
    def test_detects_missing_index(self, db):
        """Add an index to the model, detect it as missing."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            index_items = [
                item for item in items if isinstance(item.fix, CreateIndexFix)
            ]
            assert len(index_items) == 1
            assert isinstance(index_items[0].fix, CreateIndexFix)
            assert index_items[0].fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_extra_index_with_prune(self, db):
        """An index in the DB not declared on the model is extra (requires prune)."""
        execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable(
                drop_undeclared=True
            )

        index_items = [item for item in items if isinstance(item.fix, DropIndexFix)]
        assert len(index_items) == 1
        fix = index_items[0].fix
        assert isinstance(fix, DropIndexFix)
        assert fix.name == "examples_car_extra_idx"

    def test_extra_index_excluded_by_default(self, db):
        """An extra index produces no item by default."""
        execute('CREATE INDEX "examples_car_extra_idx" ON "examples_car" ("make")')

        conn = get_connection()
        with conn.cursor() as cursor:
            items = plan_model_convergence(conn, cursor, Car).executable()

        assert items == []

    def test_detects_invalid_index(self, isolated_db):
        """An INVALID index matching a model index produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        create_invalid_index("examples_car_make_idx")

        try:
            assert index_exists("examples_car_make_idx")
            assert not index_is_valid("examples_car_make_idx")

            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_detects_index_definition_changed(self, db):
        """An index with the same name but different columns produces a RebuildIndexFix."""
        original_indexes = list(Car.model_options.indexes)
        # Model declares index on "make" field
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        # DB has index on "model" column instead
        execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("model")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            rebuild_items = [
                item for item in items if isinstance(item.fix, RebuildIndexFix)
            ]
            assert len(rebuild_items) == 1
            fix = rebuild_items[0].fix
            assert isinstance(fix, RebuildIndexFix)
            assert fix.index.name == "examples_car_make_idx"
        finally:
            Car.model_options.indexes = original_indexes

    def test_no_false_positive_for_matching_index(self, db):
        """An index with matching name and matching columns produces no issues."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_idx"),
        ]

        # DB has index on "make" column — matches the model
        execute('CREATE INDEX "examples_car_make_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()

            assert items == []
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyIndexFixes:
    def test_create_index(self, isolated_db):
        """CreateIndexFix creates an index using CONCURRENTLY."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        try:
            assert not index_exists("examples_car_make_idx")

            fix = CreateIndexFix(table="examples_car", index=index, model=Car)
            sql = fix.apply()

            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes

    def test_drop_index(self, isolated_db):
        """DropIndexFix drops an index using CONCURRENTLY."""
        execute('CREATE INDEX "examples_car_temp_idx" ON "examples_car" ("make")')
        assert index_exists("examples_car_temp_idx")

        fix = DropIndexFix(table="examples_car", name="examples_car_temp_idx")
        sql = fix.apply()

        assert "CONCURRENTLY" in sql
        assert not index_exists("examples_car_temp_idx")

    def test_rebuild_invalid_index(self, isolated_db):
        """RebuildIndexFix drops an INVALID index and recreates it."""
        original_indexes = list(Car.model_options.indexes)
        index = Index(fields=["make"], name="examples_car_make_idx")
        Car.model_options.indexes = [*original_indexes, index]

        create_invalid_index("examples_car_make_idx")

        try:
            assert index_exists("examples_car_make_idx")
            assert not index_is_valid("examples_car_make_idx")

            fix = RebuildIndexFix(
                table="examples_car",
                index=index,
                model=Car,
            )
            sql = fix.apply()

            assert "DROP" in sql
            assert "CONCURRENTLY" in sql
            assert index_exists("examples_car_make_idx")
            assert index_is_valid("examples_car_make_idx")
        finally:
            Car.model_options.indexes = original_indexes


class TestApplyRenameIndex:
    def test_rename_index(self, isolated_db):
        """RenameIndexFix renames using ALTER INDEX ... RENAME TO."""
        execute('CREATE INDEX "examples_car_old_idx" ON "examples_car" ("make")')
        assert index_exists("examples_car_old_idx")

        fix = RenameIndexFix(
            table="examples_car",
            old_name="examples_car_old_idx",
            new_name="examples_car_new_idx",
        )
        sql = fix.apply()

        assert "RENAME TO" in sql
        assert not index_exists("examples_car_old_idx")
        assert index_exists("examples_car_new_idx")

    def test_rename_lifecycle(self, isolated_db):
        """Full cycle: detect rename -> apply -> detect again -> converged."""
        original_indexes = list(Car.model_options.indexes)
        Car.model_options.indexes = [
            *original_indexes,
            Index(fields=["make"], name="examples_car_make_new_idx"),
        ]
        execute('CREATE INDEX "examples_car_make_old_idx" ON "examples_car" ("make")')

        try:
            conn = get_connection()

            # First pass: detect rename
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert len(items) == 1
            assert isinstance(items[0].fix, RenameIndexFix)

            items[0].fix.apply()
            assert index_exists("examples_car_make_new_idx")
            assert not index_exists("examples_car_make_old_idx")

            # Second pass: converged
            with conn.cursor() as cursor:
                items = plan_model_convergence(conn, cursor, Car).executable()
            assert items == []
        finally:
            Car.model_options.indexes = original_indexes
