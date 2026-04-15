from __future__ import annotations

# Import submodules so @postgres.register_model runs for every test model.
from . import (  # noqa: F401
    constraints,
    defaults,
    delete,
    encrypted,
    forms,
    indexes,
    iteration,
    mixins,
    nullability,
    querysets,
    relationships,
    trees,
    unregistered,
)
