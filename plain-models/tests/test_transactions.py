"""
Tests for transaction.atomic() savepoint behavior.

These tests verify the behavioral contract of nested atomic blocks,
savepoint commit/rollback, on_commit hooks, and error recovery.
The db fixture wraps each test in an outer atomic block, so any
atomic() used here creates savepoints (not top-level transactions).
"""

from __future__ import annotations

import pytest
from app.examples.models import Car

from plain.exceptions import ValidationError
from plain.models import transaction
from plain.models.db import get_connection


class TestAtomicSavepointBasics:
    """Basic savepoint create/commit/rollback through atomic()."""

    def test_atomic_commits_on_success(self, db):
        with transaction.atomic():
            Car.query.create(make="Honda", model="Civic")

        assert Car.query.filter(make="Honda", model="Civic").exists()

    def test_atomic_rolls_back_on_exception(self, db):
        with pytest.raises(ValueError, match="boom"):  # noqa: PT012
            with transaction.atomic():
                Car.query.create(make="Honda", model="Civic")
                raise ValueError("boom")

        assert not Car.query.filter(make="Honda", model="Civic").exists()

    def test_outer_work_survives_inner_rollback(self, db):
        Car.query.create(make="Toyota", model="Camry")

        with pytest.raises(ValueError, match="boom"):  # noqa: PT012
            with transaction.atomic():
                Car.query.create(make="Honda", model="Civic")
                raise ValueError("boom")

        assert Car.query.filter(make="Toyota", model="Camry").exists()
        assert not Car.query.filter(make="Honda", model="Civic").exists()

    def test_validation_error_rolls_back_savepoint(self, db):
        Car.query.create(make="Toyota", model="Camry")

        with pytest.raises(ValidationError):
            with transaction.atomic():
                # Duplicate violates unique constraint (caught at validation)
                Car.query.create(make="Toyota", model="Camry")

        # Original row still there, outer transaction healthy
        assert Car.query.filter(make="Toyota", model="Camry").count() == 1


class TestNestedAtomic:
    """Nested atomic blocks (multiple savepoints)."""

    def test_nested_commit(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")
            with transaction.atomic():
                Car.query.create(make="Honda", model="Civic")

        assert Car.query.count() == 2

    def test_inner_rollback_preserves_outer(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")

            with pytest.raises(ValueError, match="inner boom"):  # noqa: PT012
                with transaction.atomic():
                    Car.query.create(make="Honda", model="Civic")
                    raise ValueError("inner boom")

            # Inner rolled back, outer still going
            assert Car.query.filter(make="Toyota", model="Camry").exists()
            assert not Car.query.filter(make="Honda", model="Civic").exists()

            # Can still do work in outer
            Car.query.create(make="Ford", model="F150")

        assert Car.query.filter(make="Toyota", model="Camry").exists()
        assert Car.query.filter(make="Ford", model="F150").exists()
        assert not Car.query.filter(make="Honda", model="Civic").exists()

    def test_outer_rollback_undoes_committed_inner(self, db):
        with pytest.raises(ValueError, match="outer boom"):  # noqa: PT012
            with transaction.atomic():
                with transaction.atomic():
                    Car.query.create(make="Honda", model="Civic")
                # Inner committed, but outer will roll back
                raise ValueError("outer boom")

        assert not Car.query.filter(make="Honda", model="Civic").exists()

    def test_triple_nesting(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")
            with transaction.atomic():
                Car.query.create(make="Honda", model="Civic")
                with transaction.atomic():
                    Car.query.create(make="Ford", model="F150")

        assert Car.query.count() == 3

    def test_triple_nesting_middle_rollback(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")

            with pytest.raises(ValueError, match="middle boom"):  # noqa: PT012
                with transaction.atomic():
                    Car.query.create(make="Honda", model="Civic")
                    with transaction.atomic():
                        Car.query.create(make="Ford", model="F150")
                    raise ValueError("middle boom")

            # Outer survives
            Car.query.create(make="Nissan", model="Altima")

        assert Car.query.filter(make="Toyota").exists()
        assert Car.query.filter(make="Nissan").exists()
        assert not Car.query.filter(make="Honda").exists()
        assert not Car.query.filter(make="Ford").exists()


class TestAtomicSavepointFalse:
    """atomic(savepoint=False) should not create a savepoint."""

    def test_no_savepoint_still_atomic(self, db):
        with transaction.atomic(savepoint=False):
            Car.query.create(make="Toyota", model="Camry")

        assert Car.query.filter(make="Toyota", model="Camry").exists()

    def test_no_savepoint_error_marks_rollback(self, db):
        """Without a savepoint, an error marks the outer transaction
        for rollback rather than rolling back just this block."""
        conn = get_connection()

        with pytest.raises(ValueError, match="boom"):  # noqa: PT012
            with transaction.atomic(savepoint=False):
                Car.query.create(make="Honda", model="Civic")
                raise ValueError("boom")

        # The outer transaction is now dirty
        assert conn.needs_rollback


class TestOnCommitHooks:
    """on_commit hooks should fire on commit and not fire on rollback."""

    def test_on_commit_fires_on_success(self, db):
        with transaction.atomic():
            transaction.on_commit(lambda: None)

        # Still inside the db fixture's outer atomic, so on_commit
        # hasn't fired yet (it fires when outermost commits).
        # But the hook should be registered.
        conn = get_connection()
        assert len(conn.run_on_commit) > 0

    def test_on_commit_discarded_on_rollback(self, db):
        results = []
        conn = get_connection()
        hooks_before = len(conn.run_on_commit)

        with pytest.raises(ValueError, match="boom"):  # noqa: PT012
            with transaction.atomic():
                transaction.on_commit(lambda: results.append("should not fire"))
                raise ValueError("boom")

        # Hook should have been removed by savepoint rollback
        assert len(conn.run_on_commit) == hooks_before
        assert results == []

    def test_on_commit_in_nested_rollback(self, db):
        conn = get_connection()

        with transaction.atomic():
            transaction.on_commit(lambda: None)  # outer hook
            hooks_after_outer = len(conn.run_on_commit)

            with pytest.raises(ValueError, match="boom"):  # noqa: PT012
                with transaction.atomic():
                    transaction.on_commit(lambda: None)  # inner hook
                    raise ValueError("boom")

            # Inner hook discarded, outer hook survives
            assert len(conn.run_on_commit) == hooks_after_outer


class TestSetRollback:
    """Explicit set_rollback(True) should cause rollback at savepoint exit."""

    def test_set_rollback_causes_rollback(self, db):
        with transaction.atomic():
            Car.query.create(make="Honda", model="Civic")
            conn = get_connection()
            conn.set_rollback(True)

        # The savepoint was rolled back due to set_rollback(True)
        assert not Car.query.filter(make="Honda", model="Civic").exists()


class TestAtomicDecorator:
    """atomic() works as a decorator too."""

    def test_decorator_commits(self, db):
        @transaction.atomic
        def create_car():
            Car.query.create(make="Honda", model="Civic")

        create_car()
        assert Car.query.filter(make="Honda", model="Civic").exists()

    def test_decorator_rolls_back_on_exception(self, db):
        @transaction.atomic
        def create_car():
            Car.query.create(make="Honda", model="Civic")
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            create_car()

        assert not Car.query.filter(make="Honda", model="Civic").exists()


class TestDurableAtomic:
    """Durable atomic blocks cannot be nested."""

    def test_durable_raises_when_nested(self, db):
        # db fixture creates an outer atomic with _from_testcase=True,
        # so nesting a durable block inside a non-testcase atomic should fail.
        with transaction.atomic():
            with pytest.raises(RuntimeError, match="durable"):
                with transaction.atomic(durable=True):
                    pass

    def test_durable_allowed_at_top_level(self, db):
        # Inside db fixture's _from_testcase atomic, durable is allowed
        with transaction.atomic(durable=True):
            Car.query.create(make="Honda", model="Civic")

        assert Car.query.filter(make="Honda", model="Civic").exists()


class TestConcurrentSavepoints:
    """Multiple sequential savepoints in the same transaction."""

    def test_sequential_savepoints(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")

        with transaction.atomic():
            Car.query.create(make="Honda", model="Civic")

        with transaction.atomic():
            Car.query.create(make="Ford", model="F150")

        assert Car.query.count() == 3

    def test_sequential_with_rollbacks(self, db):
        with transaction.atomic():
            Car.query.create(make="Toyota", model="Camry")

        with pytest.raises(ValueError, match="boom"):  # noqa: PT012
            with transaction.atomic():
                Car.query.create(make="Honda", model="Civic")
                raise ValueError("boom")

        with transaction.atomic():
            Car.query.create(make="Ford", model="F150")

        assert Car.query.filter(make="Toyota").exists()
        assert not Car.query.filter(make="Honda").exists()
        assert Car.query.filter(make="Ford").exists()

    def test_alternating_commit_rollback(self, db):
        """Alternating commits and rollbacks shouldn't corrupt state."""
        for i in range(5):
            if i % 2 == 0:
                with transaction.atomic():
                    Car.query.create(make=f"Make{i}", model=f"Model{i}")
            else:
                with pytest.raises(ValueError, match="boom"):  # noqa: PT012
                    with transaction.atomic():
                        Car.query.create(make=f"Make{i}", model=f"Model{i}")
                        raise ValueError("boom")

        assert Car.query.count() == 3  # i=0, 2, 4

    def test_queries_work_after_savepoint_rollback(self, db):
        """After a savepoint rollback, the connection should still be usable."""
        with pytest.raises(ValidationError):  # noqa: PT012
            with transaction.atomic():
                Car.query.create(make="Toyota", model="Camry")
                Car.query.create(make="Toyota", model="Camry")  # duplicate

        # Connection still works
        Car.query.create(make="Honda", model="Civic")
        assert Car.query.filter(make="Honda", model="Civic").exists()
