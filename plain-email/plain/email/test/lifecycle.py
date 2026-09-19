"""
Email test lifecycle, registered under the `plain.testing` entry point.

Routes EMAIL_BACKEND to the in-memory backend for the whole run — tests
never send real email — and clears the outbox before each test.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from plain.test import TestLifecycle

from ..backends.locmem import outbox

if TYPE_CHECKING:
    from plain.testing.collection import CollectedTest

_LOCMEM_BACKEND = "plain.email.backends.locmem.EmailBackend"


class EmailTestLifecycle(TestLifecycle):
    required_package = "plain.email"

    def __init__(self) -> None:
        self._original_backend: Any = None

    def setup_worker(self) -> None:
        from plain.runtime import settings

        self._original_backend = settings.EMAIL_BACKEND
        settings.EMAIL_BACKEND = _LOCMEM_BACKEND

    def teardown_worker(self) -> None:
        from plain.runtime import settings

        settings.EMAIL_BACKEND = self._original_backend

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        outbox.clear()
        yield
