from __future__ import annotations

from plain import postgres
from plain.postgres import Field, types


@postgres.register_model
class NullabilityExample(postgres.Model):
    """Minimal model for SET NOT NULL convergence tests.

    A single NOT NULL text field. Tests drop the NOT NULL via raw SQL
    to simulate drift, then verify the SetNotNullFix restores it.
    """

    required_text: Field[str] = types.TextField(max_length=100)
