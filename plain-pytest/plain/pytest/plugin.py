from __future__ import annotations

import os
from collections.abc import Generator
from typing import Any

from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

import pytest
from plain.runtime import settings as plain_settings
from plain.runtime import setup
from plain.test.otel import install_test_meter, install_test_tracer

from .browser import TestBrowser


def pytest_configure(config: Any) -> None:
    # Ensure tests run with PLAIN_ENV=test so plain.dev's dotenv loader picks
    # up `.env.test*` and skips `.env.local` for determinism. `plain test`
    # already sets this via the CLI dispatcher; this covers direct `pytest`.
    os.environ.setdefault("PLAIN_ENV", "test")

    # Opportunistically load `.env.test*` via plain.dev's loader if it's
    # installed. plain.pytest doesn't require plain.dev, so we skip silently
    # when it's absent — install plain.dev if you want `.env` loading under
    # direct `pytest` invocations. Narrow to ModuleNotFoundError so a broken
    # plain.dev install (or a renamed symbol) surfaces instead of being
    # swallowed.
    try:
        from plain.dev.dotenv import load_dotenv_files
    except ModuleNotFoundError:
        pass
    else:
        load_dotenv_files()

    # Run Plain setup before anything else
    setup()


class SettingsProxy:
    def __init__(self) -> None:
        self._original: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        return getattr(plain_settings, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            if name not in self._original:
                self._original[name] = getattr(plain_settings, name, None)
            setattr(plain_settings, name, value)

    def _restore(self) -> None:
        for key, value in self._original.items():
            setattr(plain_settings, key, value)


@pytest.fixture
def settings() -> Generator[SettingsProxy]:
    proxy = SettingsProxy()
    yield proxy
    proxy._restore()


@pytest.fixture
def otel_spans() -> InMemorySpanExporter:
    """OpenTelemetry spans emitted during the test.

    Returns the InMemorySpanExporter; call `.get_finished_spans()` to read.
    """
    exporter = install_test_tracer()
    exporter.clear()
    return exporter


@pytest.fixture
def otel_metrics() -> InMemoryMetricReader:
    """OpenTelemetry metrics emitted during the test.

    Returns the InMemoryMetricReader; call `.get_metrics_data()` or
    `.collect()` to read. Drains any prior observations on entry.
    """
    reader = install_test_meter()
    reader.get_metrics_data()  # drain
    return reader


@pytest.fixture
def testbrowser(browser: Any, request: Any) -> Generator[TestBrowser]:
    """Use playwright and pytest-playwright to run browser tests against a test server."""
    try:
        # Check if isolated_db fixture is available from the plain-postgres package.
        # If it is, then we need to run a server that has a database connection to the isolated database for this test.
        request.getfixturevalue("isolated_db")

        from plain.postgres import get_connection
        from plain.postgres.database_url import build_database_url

        # Get a database url for the isolated db that we can have the plain server connect to also.
        database_url = build_database_url(get_connection().settings_dict)
    except pytest.FixtureLookupError:
        # isolated_db fixture not available, use empty database_url
        database_url = ""

    testbrowser = TestBrowser(browser=browser, database_url=database_url)

    try:
        testbrowser.run_server()
        yield testbrowser
    finally:
        testbrowser.cleanup_server()
