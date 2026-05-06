"""OTel instrumentation tests for plain-postgres.

Covers the `db.client.connection.*` pool metric family, pool-name attribute,
response row recording, and server.* span attributes.
"""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from psycopg_pool import PoolTimeout

from plain.postgres.db import get_connection
from plain.postgres.otel import register_pool_observables
from plain.postgres.sources import runtime_pool_source
from plain.runtime import settings
from plain.test.otel import install_test_meter

# Pool observables were registered against the proxy meter at package
# `ready()`; ensure the real MeterProvider is installed and rebind so
# observations land on it.
install_test_meter()
register_pool_observables(runtime_pool_source)


def _metric_points(reader: InMemoryMetricReader, metric_name: str) -> list[Any]:
    data = reader.get_metrics_data()
    points: list[Any] = []
    if data is None:
        return points
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                if metric.name == metric_name:
                    points.extend(metric.data.data_points)
    return points


class TestQuerySpanAttributes:
    @pytest.mark.usefixtures("db")
    def test_server_address_on_span(self, otel_spans: InMemorySpanExporter) -> None:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")

        spans = [s for s in otel_spans.get_finished_spans() if s.name == "SELECT"]
        assert spans, "no SELECT span captured"
        attrs = spans[-1].attributes
        assert attrs is not None
        assert "server.address" in attrs
        # Primary semconv attr should match the supplementary network.peer.address.
        assert attrs["server.address"] == attrs.get("network.peer.address")
        assert "server.port" in attrs
        assert attrs["server.port"] == attrs.get("network.peer.port")


class TestReturnedRowsMetric:
    @pytest.mark.usefixtures("db")
    def test_select_records_returned_rows(
        self, otel_metrics: InMemoryMetricReader
    ) -> None:
        conn = get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT generate_series(1, 5)")
            cursor.fetchall()

        points = _metric_points(otel_metrics, "db.client.response.returned_rows")
        # Histogram points aggregate over collection window; at least one
        # data point with our operation tag should be present.
        select_points = [
            p for p in points if p.attributes.get("db.operation.name") == "SELECT"
        ]
        assert select_points, f"no SELECT returned_rows points; got {points}"
        # Sum across points should reflect the 5 rows we returned.
        assert sum(p.sum for p in select_points) >= 5

    @pytest.mark.usefixtures("db")
    def test_stream_records_returned_rows(
        self, otel_metrics: InMemoryMetricReader
    ) -> None:
        # Streaming uses a server-side cursor where cursor.rowcount is -1; the
        # count must come from db_span's row_count_provider closure.
        conn = get_connection()
        with conn.cursor() as cursor:
            list(cursor.stream("SELECT generate_series(1, 7)"))

        points = _metric_points(otel_metrics, "db.client.response.returned_rows")
        select_points = [
            p for p in points if p.attributes.get("db.operation.name") == "SELECT"
        ]
        assert select_points, f"no SELECT returned_rows points; got {points}"
        assert sum(p.sum for p in select_points) >= 7

    @pytest.mark.usefixtures("db")
    def test_non_select_does_not_record_returned_rows(
        self, otel_metrics: InMemoryMetricReader
    ) -> None:
        conn = get_connection()
        with conn.cursor() as cursor:
            # Table doesn't matter — a BEGIN/COMMIT compiles to COMMIT op.
            cursor.execute("SELECT 1")  # warm
        otel_metrics.get_metrics_data()  # drain

        with conn.cursor() as cursor:
            cursor.execute("CREATE TEMP TABLE _otel_tmp (v int)")
            cursor.execute("INSERT INTO _otel_tmp (v) VALUES (1), (2), (3)")
            cursor.execute("UPDATE _otel_tmp SET v = v + 1")
            cursor.execute("DELETE FROM _otel_tmp")

        points = _metric_points(otel_metrics, "db.client.response.returned_rows")
        for p in points:
            assert p.attributes.get("db.operation.name") == "SELECT", (
                f"non-SELECT recorded returned_rows: {p.attributes}"
            )


class TestPoolObservables:
    @pytest.mark.usefixtures("setup_db")
    def test_count_max_idle_pending_observed(
        self, otel_metrics: InMemoryMetricReader
    ) -> None:
        # The `db` fixture swaps in a DirectSource-backed connection that
        # bypasses the runtime pool, so exercise the pool directly.
        runtime_pool_source.close()
        held = runtime_pool_source.acquire()
        try:
            pool = runtime_pool_source._pool
            assert pool is not None
            assert pool.get_stats().get("pool_size", 0) >= 1

            otel_metrics.collect()
            data = otel_metrics.get_metrics_data()
            assert data is not None
            by_name: dict[str, list[dict[str, Any]]] = {}
            for resource_metric in data.resource_metrics:
                for scope_metric in resource_metric.scope_metrics:
                    for metric in scope_metric.metrics:
                        by_name.setdefault(metric.name, []).extend(
                            dict(p.attributes) for p in metric.data.data_points
                        )

            count_attrs = by_name.get("db.client.connection.count", [])
            states = {a.get("db.client.connection.state") for a in count_attrs}
            assert "idle" in states, count_attrs
            assert "used" in states, count_attrs
            for a in count_attrs:
                assert a.get("db.client.connection.pool.name") == "runtime"

            for name in (
                "db.client.connection.max",
                "db.client.connection.idle.min",
                "db.client.connection.idle.max",
                "db.client.connection.pending_requests",
            ):
                attrs_list = by_name.get(name, [])
                assert attrs_list, f"no observations for {name}"
                for a in attrs_list:
                    assert a.get("db.client.connection.pool.name") == "runtime"
        finally:
            runtime_pool_source.release(held)
            runtime_pool_source.close()


class TestWaitTimeHistogram:
    @pytest.mark.usefixtures("db")
    def test_wait_time_under_contention(
        self,
        monkeypatch: pytest.MonkeyPatch,
        otel_metrics: InMemoryMetricReader,
    ) -> None:
        # Rebuild the pool at size 1 so a second concurrent acquire must wait.
        runtime_pool_source.close()
        monkeypatch.setattr(settings, "POSTGRES_POOL_MIN_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_MAX_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_TIMEOUT", 2.0)
        try:
            held = runtime_pool_source.acquire()
            release_event = threading.Event()

            def _second() -> None:
                # Will block until `held` is released.
                conn = runtime_pool_source.acquire()
                runtime_pool_source.release(conn)

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_second)
                # Give the thread time to start blocking on the pool.
                threading.Event().wait(0.15)
                runtime_pool_source.release(held)
                release_event.set()
                fut.result(timeout=3.0)

            otel_metrics.collect()
            points = _metric_points(otel_metrics, "db.client.connection.wait_time")
            relevant = [
                p
                for p in points
                if p.attributes.get("db.client.connection.pool.name") == "runtime"
            ]
            assert relevant, f"no wait_time observations; got {points}"
            # Second acquire waited noticeably.
            assert max(p.max for p in relevant) >= 0.1
        finally:
            runtime_pool_source.close()


class TestTimeoutCounter:
    @pytest.mark.usefixtures("db")
    def test_pool_timeout_increments_counter(
        self,
        monkeypatch: pytest.MonkeyPatch,
        otel_metrics: InMemoryMetricReader,
    ) -> None:
        runtime_pool_source.close()
        monkeypatch.setattr(settings, "POSTGRES_POOL_MIN_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_MAX_SIZE", 1)
        monkeypatch.setattr(settings, "POSTGRES_POOL_TIMEOUT", 0.15)
        try:
            held = runtime_pool_source.acquire()
            try:
                with pytest.raises(PoolTimeout):
                    runtime_pool_source.acquire()
            finally:
                runtime_pool_source.release(held)

            otel_metrics.collect()
            points = _metric_points(otel_metrics, "db.client.connection.timeouts")
            relevant = [
                p
                for p in points
                if p.attributes.get("db.client.connection.pool.name") == "runtime"
            ]
            assert relevant, f"no timeouts observations; got {points}"
            assert sum(p.value for p in relevant) >= 1
        finally:
            runtime_pool_source.close()
