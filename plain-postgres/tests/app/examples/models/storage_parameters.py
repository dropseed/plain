from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class StorageParametersExample(postgres.Model):
    """Dedicated to storage-parameter convergence tests so in-place mutations
    of `model_options.storage_parameters` don't leak into other suites."""

    name: Field[str] = types.TextField(max_length=100)
