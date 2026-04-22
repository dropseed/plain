"""
Tests for the read_only() context manager.

read_only() opens a single BEGIN READ ONLY transaction for the block,
so writes raise and nested atomic() blocks become read-only savepoints.
"""

from __future__ import annotations

import psycopg.errors
import pytest
from app.examples.models.iteration import IterationExample

from plain.postgres import transaction
from plain.postgres.db import read_only
from plain.postgres.transaction import TransactionManagementError


class TestReadOnly:
    def test_blocks_writes(self, isolated_db):
        with read_only():
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                IterationExample.query.create(name="Toyota", tag="Tundra")

    def test_allows_reads(self, isolated_db):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            assert IterationExample.query.count() == 1
            assert IterationExample.query.filter(name="Toyota").exists()

    def test_writable_after_exit(self, isolated_db):
        with read_only():
            assert IterationExample.query.count() == 0

        IterationExample.query.create(name="Toyota", tag="Tundra")
        assert IterationExample.query.count() == 1

    def test_nested_atomic_inherits_read_only(self, isolated_db):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            with transaction.atomic():
                assert IterationExample.query.count() == 1
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    IterationExample.query.create(name="Ford", tag="F150")

    def test_cannot_enter_inside_atomic(self, isolated_db):
        with transaction.atomic():
            with pytest.raises(
                TransactionManagementError,
                match="read_only.*cannot be entered inside an existing atomic",
            ):
                with read_only():
                    pass

    def test_exception_leaves_connection_writable(self, isolated_db):
        with pytest.raises(RuntimeError):
            with read_only():
                raise RuntimeError("boom")

        # Connection is writable again after the block unwinds.
        IterationExample.query.create(name="Toyota", tag="Tundra")
        assert IterationExample.query.count() == 1

    def test_caught_write_poisons_remainder_of_block(self, isolated_db):
        # read_only() opens a single transaction for the whole block, so a
        # caught write error leaves the txn aborted — subsequent queries in
        # the same block fail with TransactionManagementError. Callers that
        # need to keep reading after catching a write must wrap the write in
        # a nested atomic() (see test_nested_atomic_rescues_caught_write).
        with read_only():
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                IterationExample.query.create(name="Toyota", tag="Tundra")
            with pytest.raises(
                TransactionManagementError,
                match="An error occurred in the current transaction",
            ):
                IterationExample.query.count()

    def test_nested_atomic_rescues_caught_write(self, isolated_db):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                with transaction.atomic():
                    IterationExample.query.create(name="Ford", tag="F150")
            # The savepoint rolled back, so the outer read-only txn is
            # healthy and reads continue to work.
            assert IterationExample.query.count() == 1
