from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class StorageParametersExample(postgres.Model):
    """Dedicated to storage-parameter convergence tests so in-place mutations
    of `model_options.storage_parameters` don't leak into other suites."""

    name = types.TextField(max_length=100)

    query: postgres.QuerySet[StorageParametersExample] = postgres.QuerySet()
