from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from .base import Operation

if TYPE_CHECKING:
    from plain.models.backends.base.schema import BaseDatabaseSchemaEditor
    from plain.models.migrations.state import ProjectState


class SeparateDatabaseAndState(Operation):
    """
    Take two lists of operations - ones that will be used for the database,
    and ones that will be used for the state change. This allows operations
    that don't support state change to have it applied, or have operations
    that affect the state or not the database, or so on.
    """

    serialization_expand_args = ["database_operations", "state_operations"]

    def __init__(
        self,
        database_operations: list[Operation] | None = None,
        state_operations: list[Operation] | None = None,
    ) -> None:
        self.database_operations = database_operations or []
        self.state_operations = state_operations or []

    def deconstruct(self) -> tuple[str, list[Any], dict[str, list[Operation]]]:
        kwargs: dict[str, list[Operation]] = {}
        if self.database_operations:
            kwargs["database_operations"] = self.database_operations
        if self.state_operations:
            kwargs["state_operations"] = self.state_operations
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        for state_operation in self.state_operations:
            state_operation.state_forwards(package_label, state)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        # We calculate state separately in here since our state functions aren't useful
        for database_operation in self.database_operations:
            to_state = from_state.clone()
            database_operation.state_forwards(package_label, to_state)
            database_operation.database_forwards(
                package_label, schema_editor, from_state, to_state
            )
            from_state = to_state

    def describe(self) -> str:
        return "Custom state/database change combination"


class RunSQL(Operation):
    """
    Run some raw SQL.

    Also accept a list of operations that represent the state change effected
    by this SQL change, in case it's custom column/table creation/deletion.
    """

    def __init__(
        self,
        sql: str
        | list[str | tuple[str, list[Any]]]
        | tuple[str | tuple[str, list[Any]], ...],
        *,
        state_operations: list[Operation] | None = None,
        elidable: bool = False,
    ) -> None:
        self.sql = sql
        self.state_operations = state_operations or []
        self.elidable = elidable

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "sql": self.sql,
        }
        if self.state_operations:
            kwargs["state_operations"] = self.state_operations
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: ProjectState) -> None:
        for state_operation in self.state_operations:
            state_operation.state_forwards(package_label, state)

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        self._run_sql(schema_editor, self.sql)

    def describe(self) -> str:
        return "Raw SQL operation"

    def _run_sql(
        self,
        schema_editor: BaseDatabaseSchemaEditor,
        sqls: str
        | list[str | tuple[str, list[Any]]]
        | tuple[str | tuple[str, list[Any]], ...],
    ) -> None:
        if isinstance(sqls, list | tuple):
            for sql_item in sqls:
                params: list[Any] | None = None
                sql: str
                if isinstance(sql_item, list | tuple):
                    elements = len(sql_item)
                    if elements == 2:
                        sql, params = sql_item  # type: ignore[misc]
                    else:
                        raise ValueError("Expected a 2-tuple but got %d" % elements)  # noqa: UP031
                else:
                    sql = sql_item
                schema_editor.execute(sql, params=params)
        else:
            # sqls is a str in this branch
            statements = schema_editor.connection.ops.prepare_sql_script(
                cast(str, sqls)
            )
            for statement in statements:
                schema_editor.execute(statement, params=None)


class RunPython(Operation):
    """
    Run Python code in a context suitable for doing versioned ORM operations.
    """

    reduces_to_sql = False

    def __init__(
        self,
        code: Callable[..., Any],
        *,
        atomic: bool | None = None,
        elidable: bool = False,
    ) -> None:
        self.atomic = atomic
        # Forwards code
        if not callable(code):
            raise ValueError("RunPython must be supplied with a callable")
        self.code = code
        self.elidable = elidable

    def deconstruct(self) -> tuple[str, list[Any], dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "code": self.code,
        }
        if self.atomic is not None:
            kwargs["atomic"] = self.atomic
        return (self.__class__.__qualname__, [], kwargs)

    def state_forwards(self, package_label: str, state: Any) -> None:
        # RunPython objects have no state effect. To add some, combine this
        # with SeparateDatabaseAndState.
        pass

    def database_forwards(
        self,
        package_label: str,
        schema_editor: BaseDatabaseSchemaEditor,
        from_state: ProjectState,
        to_state: ProjectState,
    ) -> None:
        # RunPython has access to all models. Ensure that all models are
        # reloaded in case any are delayed.
        from_state.clear_delayed_models_cache()
        # We now execute the Python code in a context that contains a 'models'
        # object, representing the versioned models as an app registry.
        # We could try to override the global cache, but then people will still
        # use direct imports, so we go with a documentation approach instead.
        self.code(from_state.models_registry, schema_editor)

    def describe(self) -> str:
        return "Raw Python operation"
