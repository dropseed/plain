"""
Email test lifecycle, registered under the `plain.testing` entry point.

Routes EMAIL_BACKEND to the in-memory backend for the whole run — tests
never send real email — and clears the outbox around each test.
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
    def __init__(self) -> None:
        self._original_backend: Any = None
        self._active = False

    def setup_worker(self) -> None:
        from plain.runtime import settings

        # The entry point loads whenever plain.email is importable, but the
        # lifecycle only applies when the app actually installs it.
        self._active = "plain.email" in settings.INSTALLED_PACKAGES
        if not self._active:
            return

        self._original_backend = settings.EMAIL_BACKEND
        settings.EMAIL_BACKEND = _LOCMEM_BACKEND

    def teardown_worker(self) -> None:
        if not self._active:
            return

        from plain.runtime import settings

        settings.EMAIL_BACKEND = self._original_backend
        outbox.clear()

    @contextmanager
    def around_test(self, test: CollectedTest) -> Generator[None]:
        if not self._active:
            yield
            return

        outbox.clear()
        try:
            yield
        finally:
            outbox.clear()
