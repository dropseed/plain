"""OTel instrumentation tests for plain-postgres.

Covers the `db.client.connection.*` pool metric family, pool-name attribute,
response row recording, and server.* span attributes.
"""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.trace import NoOpTracer
from psycopg_pool import PoolTimeout

from plain.postgres import otel as postgres_otel
from plain.postgres.db import get_connection
from plain.postgres.otel import register_pool_observables
from plain.postgres.sources import runtime_pool_source
from plain.test import capture_metrics, capture_spans, override_settings, patch, raises
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
    def test_server_address_on_span(self) -> None:
        with capture_spans() as otel_spans:
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

    def test_not_recording_skips_stack_walk(self) -> None:
        # Cheap attributes still build unconditionally (attribute-aware
        # samplers see them at span creation), but the per-query stack walk
        # must only happen when the span actually records.
        stack_walks: list[int] = []

        def counting_code_attributes() -> dict[str, Any]:
            stack_walks.append(1)
            return {}

        class StubDb:
            settings_dict: dict[str, Any] = {}

        with (
            patch(postgres_otel, "_get_code_attributes", counting_code_attributes),
            patch(postgres_otel, "tracer", NoOpTracer()),
        ):
            with postgres_otel.db_span(StubDb(), "SELECT 1") as span:  # ty: ignore[invalid-argument-type]
                pass

        assert span is not None
        assert not span.is_recording()
        assert not stack_walks


class TestReturnedRowsMetric:
    def test_select_records_returned_rows(self) -> None:
        with capture_metrics() as otel_metrics:
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

    def test_stream_records_returned_rows(self) -> None:
        # Streaming uses a server-side cursor where cursor.rowcount is -1; the
        # count must come from db_span's row_count_provider closure.
        with capture_metrics() as otel_metrics:
            conn = get_connection()
            with conn.cursor() as cursor:
                list(cursor.stream("SELECT generate_series(1, 7)"))

            points = _metric_points(otel_metrics, "db.client.response.returned_rows")
        select_points = [
            p for p in points if p.attributes.get("db.operation.name") == "SELECT"
        ]
        assert select_points, f"no SELECT returned_rows points; got {points}"
        assert sum(p.sum for p in select_points) >= 7

    def test_non_select_does_not_record_returned_rows(self) -> None:
        with capture_metrics() as otel_metrics:
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
    def test_count_max_idle_pending_observed(self) -> None:
        # The per-test transaction runs on a connection that bypasses the
        # runtime pool, so exercise the pool directly.
        with capture_metrics() as otel_metrics:
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
    def test_wait_time_under_contention(self) -> None:
        # Rebuild the pool at size 1 so a second concurrent acquire must wait.
        with capture_metrics() as otel_metrics:
            runtime_pool_source.close()
            try:
                with override_settings(
                    POSTGRES_POOL_MIN_SIZE=1,
                    POSTGRES_POOL_MAX_SIZE=1,
                    POSTGRES_POOL_TIMEOUT=2.0,
                ):
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
    def test_pool_timeout_increments_counter(self) -> None:
        with capture_metrics() as otel_metrics:
            runtime_pool_source.close()
            try:
                with override_settings(
                    POSTGRES_POOL_MIN_SIZE=1,
                    POSTGRES_POOL_MAX_SIZE=1,
                    POSTGRES_POOL_TIMEOUT=0.15,
                ):
                    held = runtime_pool_source.acquire()
                    try:
                        with raises(PoolTimeout):
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
