from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class IndexExample(postgres.Model):
    """Minimal model for index-convergence tests.

    Two text fields. Tests mutate `model_options.indexes` in-place to
    simulate drift; keeping this fixture dedicated means those mutations
    never leak into other test files' schemas.
    """

    name: str = types.TextField(max_length=100)
    description: str = types.TextField(max_length=100)

    query: postgres.QuerySet[IndexExample] = postgres.QuerySet()
