"""
Tests for read-only database connection support.

Tests both the scoped context manager (read_only()) and the
connection-level method (get_connection().set_read_only()).

Uses isolated_db because SET default_transaction_read_only only
affects the next transaction — the db fixture's wrapping transaction
is already in progress.
"""

from __future__ import annotations

import pytest
from app.examples.models import Car

from plain.postgres import transaction
from plain.postgres.connections import read_only
from plain.postgres.db import ReadOnlyError, get_connection
from plain.postgres.transaction import TransactionManagementError


class TestReadOnlyContextManager:
    def test_blocks_writes(self, isolated_db):
        with read_only():
            with pytest.raises(ReadOnlyError, match="read-only transaction"):
                Car.query.create(make="Toyota", model="Tundra")

    def test_allows_reads(self, isolated_db):
        Car.query.create(make="Toyota", model="Tundra")
        with read_only():
            assert Car.query.count() == 1
            assert Car.query.filter(make="Toyota").exists()

    def test_writable_after_exit(self, isolated_db):
        with read_only():
            assert Car.query.count() == 0

        Car.query.create(make="Toyota", model="Tundra")
        assert Car.query.count() == 1

    def test_with_atomic(self, isolated_db):
        Car.query.create(make="Toyota", model="Tundra")
        with read_only():
            with transaction.atomic():
                assert Car.query.count() == 1

    def test_blocks_in_atomic(self, isolated_db):
        with read_only():
            with pytest.raises(ReadOnlyError, match="read-only transaction"):
                with transaction.atomic():
                    Car.query.create(make="Toyota", model="Tundra")

    def test_inside_atomic_raises(self, isolated_db):
        with transaction.atomic():
            with pytest.raises(
                TransactionManagementError,
                match="set_read_only.*cannot be called inside a transaction",
            ):
                with read_only():
                    pass


class TestReadOnlyInsideTransaction:
    def test_read_only_context_mgr_raises(self, db):
        with pytest.raises(
            TransactionManagementError,
            match="set_read_only.*cannot be called inside a transaction",
        ):
            with read_only():
                pass

    def test_set_read_only_raises(self, db):
        conn = get_connection()
        with pytest.raises(
            TransactionManagementError,
            match="set_read_only.*cannot be called inside a transaction",
        ):
            conn.set_read_only(True)


class TestSetReadOnly:
    def test_blocks_writes(self, isolated_db):
        conn = get_connection()
        conn.set_read_only(True)
        try:
            with pytest.raises(ReadOnlyError, match="read-only transaction"):
                Car.query.create(make="Toyota", model="Tundra")
        finally:
            conn.set_read_only(False)

    def test_allows_reads(self, isolated_db):
        Car.query.create(make="Toyota", model="Tundra")
        conn = get_connection()
        conn.set_read_only(True)
        try:
            assert Car.query.count() == 1
        finally:
            conn.set_read_only(False)

    def test_disable_restores(self, isolated_db):
        conn = get_connection()
        conn.set_read_only(True)
        conn.set_read_only(False)
        Car.query.create(make="Toyota", model="Tundra")
        assert Car.query.count() == 1

    def test_inside_atomic_raises(self, isolated_db):
        conn = get_connection()
        with transaction.atomic():
            with pytest.raises(
                TransactionManagementError,
                match="set_read_only.*cannot be called inside a transaction",
            ):
                conn.set_read_only(True)
