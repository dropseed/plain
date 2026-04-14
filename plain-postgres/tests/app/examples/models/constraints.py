from __future__ import annotations

from plain import postgres
from plain.postgres import types


@postgres.register_model
class ConstraintExample(postgres.Model):
    """Minimal model for constraint-convergence tests.

    Two text fields + a unique constraint on the pair. The convergence
    tests add/drop/rename check and unique constraints against this
    fixture without polluting other models' schemas.
    """

    name: str = types.TextField(max_length=100)
    description: str = types.TextField(max_length=100)

    query: postgres.QuerySet[ConstraintExample] = postgres.QuerySet()

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name", "description"],
                name="unique_constraintexample_name_description",
            ),
        ]
    )
