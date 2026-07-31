from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class ConstraintExample(postgres.Model):
    """Minimal model for constraint-convergence tests.

    Two text fields + a unique constraint on the pair. The convergence
    tests add/drop/rename check and unique constraints against this
    fixture without polluting other models' schemas.
    """

    name: Field[str] = types.TextField(max_length=100)
    description: Field[str] = types.TextField(max_length=100)

    model_options = postgres.Options(
        constraints=[
            postgres.UniqueConstraint(
                fields=["name", "description"],
                name="unique_constraintexample_name_description",
            ),
        ]
    )
