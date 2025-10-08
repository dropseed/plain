from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.backends.base.base import BaseDatabaseWrapper
    from plain.models.backends.base.schema import BaseDatabaseSchemaEditor
    from plain.models.migrations.state import ProjectState


class Operation:
    """
    Base class for migration operations.

    It's responsible for both mutating the in-memory model state
    (see db/migrations/state.py) to represent what it performs, as well
    as actually performing it against a live database.

    Note that some operations won't modify memory state at all (e.g. data
    copying operations), and some will need their modifications to be
    optionally specified by the user (e.g. custom Python code snippets)

    Due to the way this class deals with deconstruction, it should be
    considered immutable.
    """

    # Can this migration be represented as SQL? (things like RunPython cannot)
    reduces_to_sql = True

    # Should this operation be forced as atomic even on backends with no
    # DDL transaction support (i.e., does it have no DDL, like RunPython)
    atomic = False

    # Should this operation be considered safe to elide and optimize across?
    elidable = False

    serialization_expand_args: list[str] = []

    def __new__(cls, *args: Any, **kwargs: Any) -> Operation:
        # We capture the arguments to make returning them trivial
        self = object.__new__(cls)
        self._constructor_args = (args, kwargs)  # type: ignore[attr-defined]
        return self  # type: ignore[return-value]

    def deconstruct(self) -> tuple[str, tuple[Any, ...], dict[str, Any]]:
        """
        Return a 3-tuple of class import path (or just name if it lives
        under plain.models.migrations), positional arguments, and keyword
        arguments.
        """
        return (
            self.__class__.__name__,
            self._constructor_args[0],  # type: ignore[attr-defined]
            self._constructor_args[1],  # type: ignore[attr-defined]
        )

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        """
        Take the state from the previous migration, and mutate it
        so that it matches what this migration would perform.
        """
        raise NotImplementedError(
            "subclasses of Operation must provide a state_forwards() method"
        )

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        """
        Perform the mutation on the database schema in the normal
        (forwards) direction.
        """
        raise NotImplementedError(
            "subclasses of Operation must provide a database_forwards() method"
        )

    def describe(self) -> str:
        """
        Output a brief summary of what the action does.
        """
        return f"{self.__class__.__name__}: {self._constructor_args}"  # type: ignore[attr-defined]

    @property
    def migration_name_fragment(self) -> str | None:
        """
        A filename part suitable for automatically naming a migration
        containing this operation, or None if not applicable.
        """
        return None

    def references_model(self, name: str, package_label: str) -> bool:
        """
        Return True if there is a chance this operation references the given
        model name (as a string), with an app label for accuracy.

        Used for optimization. If in doubt, return True;
        returning a false positive will merely make the optimizer a little
        less efficient, while returning a false negative may result in an
        unusable optimized migration.
        """
        return True

    def references_field(self, model_name: str, name: str, package_label: str) -> bool:
        """
        Return True if there is a chance this operation references the given
        field name, with an app label for accuracy.

        Used for optimization. If in doubt, return True.
        """
        return self.references_model(model_name, package_label)

    def allow_migrate_model(self, connection: BaseDatabaseWrapper, model: Any) -> bool:
        """Return whether or not a model may be migrated."""
        if not model.model_options.can_migrate(connection):
            return False

        return True

    def reduce(
        self, operation: Operation, package_label: str
    ) -> list[Operation] | bool:
        """
        Return either a list of operations the actual operation should be
        replaced with or a boolean that indicates whether or not the specified
        operation can be optimized across.
        """
        if self.elidable:
            return [operation]
        elif operation.elidable:
            return [self]
        return False

    def __repr__(self) -> str:
        return "<{} {}{}>".format(
            self.__class__.__name__,
            ", ".join(map(repr, self._constructor_args[0])),  # type: ignore[attr-defined]
            ",".join(" {}={!r}".format(*x) for x in self._constructor_args[1].items()),  # type: ignore[attr-defined]
        )
