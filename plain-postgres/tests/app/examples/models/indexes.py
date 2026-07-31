from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class IndexExample(postgres.Model):
    """Minimal model for index-convergence tests.

    Two text fields. Tests mutate `model_options.indexes` in-place to
    simulate drift; keeping this fixture dedicated means those mutations
    never leak into other test files' schemas.
    """

    name: Field[str] = types.TextField(max_length=100)
    description: Field[str] = types.TextField(max_length=100)
