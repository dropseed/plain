from __future__ import annotations

from typing import Any

from plain.models.db import DatabaseError


class AmbiguityError(Exception):
    """More than one migration matches a name prefix."""

    pass


class BadMigrationError(Exception):
    """There's a bad migration (unreadable/bad format/etc.)."""

    pass


class CircularDependencyError(Exception):
    """There's an impossible-to-resolve circular dependency."""

    pass


class InconsistentMigrationHistory(Exception):
    """An applied migration has some of its dependencies not applied."""

    pass


class InvalidBasesError(ValueError):
    """A model's base classes can't be resolved."""

    pass


class NodeNotFoundError(LookupError):
    """An attempt on a node is made that is not available in the graph."""

    def __init__(self, message: str, node: Any, origin: Any = None) -> None:
        self.message = message
        self.origin = origin
        self.node = node

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"NodeNotFoundError({self.node!r})"


class MigrationSchemaMissing(DatabaseError):
    pass
