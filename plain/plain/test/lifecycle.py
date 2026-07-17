"""
The extension point for the test runner (plain.testing).

Packages that participate in testing subclass TestLifecycle and register it
under the `plain.testing` entry point group:

    [project.entry-points."plain.testing"]
    postgres = "plain.postgres.test.lifecycle:PostgresTestLifecycle"

The runner discovers and drives lifecycles; packages never import the runner.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plain.testing.collection import CollectedTest

__all__ = ["TestLifecycle"]


class TestLifecycle:
    # When set, the lifecycle only loads if this package is in the app's
    # INSTALLED_PACKAGES — the entry point is importable whenever the package
    # is in the environment, which is a wider net than "the app uses it".
    required_package: str | None = None

    def setup_worker(self) -> None:
        """Called once per worker process, before any tests run."""

    def teardown_worker(self) -> None:
        """Called once per worker process, after all tests have run."""

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        """
        Wrap a single test. `test.tags` carries any `@tag(...)` labels, which
        lifecycles can use to vary behavior per-test.
        """
        yield
