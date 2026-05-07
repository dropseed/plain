from __future__ import annotations

from app.examples.models.storage_parameters import StorageParametersExample
from conftest_convergence import execute

from plain.postgres import get_connection
from plain.postgres.convergence import (
    ResetStorageParameterFix,
    SetStorageParameterFix,
    plan_model_convergence,
)
from plain.postgres.convergence.analysis import (
    DriftKind,
    StorageParameterDrift,
    analyze_model,
)
from plain.postgres.introspection.schema import _fetch_raw_reloptions


def _table_reloptions(table: str) -> tuple[list[str] | None, list[str] | None]:
    with get_connection().cursor() as cursor:
        return _fetch_raw_reloptions(cursor, table)


def _set_params(model, params: dict[str, str]) -> None:
    model.model_options.storage_parameters = dict(params)


class TestStorageParameterDriftDetection:
    def test_missing_param_detected(self, db):
        original = dict(StorageParametersExample.model_options.storage_parameters)
        _set_params(StorageParametersExample, {"autovacuum_vacuum_scale_factor": "0.1"})

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, StorageParametersExample)

            drifts = [
                d for d in analysis.drifts if isinstance(d, StorageParameterDrift)
            ]
            assert len(drifts) == 1
            assert drifts[0].kind == DriftKind.MISSING
            assert drifts[0].key == "autovacuum_vacuum_scale_factor"
            assert drifts[0].declared_value == "0.1"
        finally:
            _set_params(StorageParametersExample, original)

    def test_changed_param_detected(self, db):
        original = dict(StorageParametersExample.model_options.storage_parameters)
        _set_params(StorageParametersExample, {"autovacuum_vacuum_scale_factor": "0.1"})

        try:
            execute(
                'ALTER TABLE "examples_storageparametersexample"'
                " SET (autovacuum_vacuum_scale_factor = '0.2')"
            )

            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, StorageParametersExample)

            drifts = [
                d for d in analysis.drifts if isinstance(d, StorageParameterDrift)
            ]
            assert len(drifts) == 1
            assert drifts[0].kind == DriftKind.CHANGED
            assert drifts[0].declared_value == "0.1"
            assert drifts[0].actual_value == "0.2"
        finally:
            execute(
                'ALTER TABLE "examples_storageparametersexample"'
                " RESET (autovacuum_vacuum_scale_factor)"
            )
            _set_params(StorageParametersExample, original)

    def test_undeclared_param_detected(self, db):
        execute('ALTER TABLE "examples_storageparametersexample" SET (fillfactor = 90)')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, StorageParametersExample)

            drifts = [
                d for d in analysis.drifts if isinstance(d, StorageParameterDrift)
            ]
            assert any(
                d.kind == DriftKind.UNDECLARED and d.key == "fillfactor" for d in drifts
            )
        finally:
            execute(
                'ALTER TABLE "examples_storageparametersexample" RESET (fillfactor)'
            )

    def test_toast_param_detected(self, db):
        original = dict(StorageParametersExample.model_options.storage_parameters)
        _set_params(
            StorageParametersExample,
            {"toast.autovacuum_vacuum_scale_factor": "0.05"},
        )

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                analysis = analyze_model(conn, cursor, StorageParametersExample)

            drifts = [
                d for d in analysis.drifts if isinstance(d, StorageParameterDrift)
            ]
            assert len(drifts) == 1
            assert drifts[0].kind == DriftKind.MISSING
            assert drifts[0].key == "toast.autovacuum_vacuum_scale_factor"
        finally:
            _set_params(StorageParametersExample, original)


class TestStorageParameterPlanning:
    def test_missing_plans_set_fix(self, db):
        original = dict(StorageParametersExample.model_options.storage_parameters)
        _set_params(StorageParametersExample, {"autovacuum_vacuum_scale_factor": "0.1"})

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, StorageParametersExample
                ).executable()

            set_fixes = [
                item.fix
                for item in items
                if isinstance(item.fix, SetStorageParameterFix)
            ]
            assert len(set_fixes) == 1
            assert set_fixes[0].key == "autovacuum_vacuum_scale_factor"
            assert set_fixes[0].value == "0.1"
        finally:
            _set_params(StorageParametersExample, original)

    def test_undeclared_plans_reset_fix(self, db):
        execute('ALTER TABLE "examples_storageparametersexample" SET (fillfactor = 90)')

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, StorageParametersExample
                ).executable()

            reset_fixes = [
                item.fix
                for item in items
                if isinstance(item.fix, ResetStorageParameterFix)
            ]
            assert len(reset_fixes) == 1
            assert reset_fixes[0].key == "fillfactor"
        finally:
            execute(
                'ALTER TABLE "examples_storageparametersexample" RESET (fillfactor)'
            )


class TestStorageParameterApply:
    def test_set_fix_applies_heap_param(self, isolated_db):
        fix = SetStorageParameterFix(
            table="examples_storageparametersexample",
            key="autovacuum_vacuum_scale_factor",
            value="0.1",
        )

        fix.apply()
        heap, _ = _table_reloptions("examples_storageparametersexample")
        assert heap is not None
        assert "autovacuum_vacuum_scale_factor=0.1" in heap

    def test_set_fix_applies_toast_param(self, isolated_db):
        fix = SetStorageParameterFix(
            table="examples_storageparametersexample",
            key="toast.autovacuum_vacuum_scale_factor",
            value="0.05",
        )

        fix.apply()
        _, toast = _table_reloptions("examples_storageparametersexample")
        assert toast is not None
        assert "autovacuum_vacuum_scale_factor=0.05" in toast

    def test_reset_fix_clears_param(self, isolated_db):
        execute('ALTER TABLE "examples_storageparametersexample" SET (fillfactor = 90)')

        fix = ResetStorageParameterFix(
            table="examples_storageparametersexample", key="fillfactor"
        )
        fix.apply()

        heap, _ = _table_reloptions("examples_storageparametersexample")
        assert heap is None or not any("fillfactor" in opt for opt in heap)

    def test_idempotent_after_apply(self, isolated_db):
        original = dict(StorageParametersExample.model_options.storage_parameters)
        _set_params(StorageParametersExample, {"autovacuum_vacuum_scale_factor": "0.1"})

        try:
            conn = get_connection()
            with conn.cursor() as cursor:
                items = plan_model_convergence(
                    conn, cursor, StorageParametersExample
                ).executable()
            for item in items:
                assert item.fix is not None
                item.fix.apply()

            with get_connection().cursor() as cursor:
                analysis = analyze_model(
                    get_connection(), cursor, StorageParametersExample
                )
            assert not [
                d for d in analysis.drifts if isinstance(d, StorageParameterDrift)
            ]
        finally:
            _set_params(StorageParametersExample, original)
