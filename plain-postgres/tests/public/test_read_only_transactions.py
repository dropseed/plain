"""
Tests for the read_only() context manager.

read_only() opens a single BEGIN READ ONLY transaction for the block,
so writes raise and nested atomic() blocks become read-only savepoints.
"""

from __future__ import annotations

import psycopg.errors
from app.examples.models.iteration import IterationExample

from plain.postgres import transaction
from plain.postgres.db import read_only
from plain.postgres.test import isolated_db
from plain.postgres.transaction import TransactionManagementError
from plain.test import raises


class TestReadOnly:
    @isolated_db
    def test_blocks_writes(self):
        with read_only():
            with raises(psycopg.errors.ReadOnlySqlTransaction):
                IterationExample.query.create(name="Toyota", tag="Tundra")

    @isolated_db
    def test_allows_reads(self):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            assert IterationExample.query.count() == 1
            assert IterationExample.query.filter(name="Toyota").exists()

    @isolated_db
    def test_writable_after_exit(self):
        with read_only():
            assert IterationExample.query.count() == 0

        IterationExample.query.create(name="Toyota", tag="Tundra")
        assert IterationExample.query.count() == 1

    @isolated_db
    def test_nested_atomic_inherits_read_only(self):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            with transaction.atomic():
                assert IterationExample.query.count() == 1
                with raises(psycopg.errors.ReadOnlySqlTransaction):
                    IterationExample.query.create(name="Ford", tag="F150")

    @isolated_db
    def test_cannot_enter_inside_atomic(self):
        with transaction.atomic():
            with raises(
                TransactionManagementError,
                match="read_only.*cannot be entered inside an existing atomic",
            ):
                with read_only():
                    pass

    @isolated_db
    def test_exception_leaves_connection_writable(self):
        with raises(RuntimeError):
            with read_only():
                raise RuntimeError("boom")

        # Connection is writable again after the block unwinds.
        IterationExample.query.create(name="Toyota", tag="Tundra")
        assert IterationExample.query.count() == 1

    @isolated_db
    def test_caught_write_poisons_remainder_of_block(self):
        # read_only() opens a single transaction for the whole block, so a
        # caught write error leaves the txn aborted — subsequent queries in
        # the same block fail with TransactionManagementError. Callers that
        # need to keep reading after catching a write must wrap the write in
        # a nested atomic() (see test_nested_atomic_rescues_caught_write).
        with read_only():
            with raises(psycopg.errors.ReadOnlySqlTransaction):
                IterationExample.query.create(name="Toyota", tag="Tundra")
            with raises(
                TransactionManagementError,
                match="An error occurred in the current transaction",
            ):
                IterationExample.query.count()

    @isolated_db
    def test_nested_atomic_rescues_caught_write(self):
        IterationExample.query.create(name="Toyota", tag="Tundra")
        with read_only():
            with raises(psycopg.errors.ReadOnlySqlTransaction):
                with transaction.atomic():
                    IterationExample.query.create(name="Ford", tag="F150")
            # The savepoint rolled back, so the outer read-only txn is
            # healthy and reads continue to work.
            assert IterationExample.query.count() == 1
