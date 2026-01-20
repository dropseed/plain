from ..backends.base.schema import BaseDatabaseSchemaEditor
from .migration import Migration, settings_dependency
from .operations import (
    AddConstraint,
    AddField,
    AddIndex,
    AlterField,
    AlterModelOptions,
    AlterModelTable,
    AlterModelTableComment,
    CreateModel,
    DeleteModel,
    RemoveConstraint,
    RemoveField,
    RemoveIndex,
    RenameField,
    RenameIndex,
    RenameModel,
    RunPython,
    RunSQL,
    SeparateDatabaseAndState,
)
from .state import StateModelsRegistry

__all__ = [
    # Migration class
    "Migration",
    "settings_dependency",
    # Model operations
    "CreateModel",
    "DeleteModel",
    "AlterModelTable",
    "AlterModelTableComment",
    "RenameModel",
    "AlterModelOptions",
    # Field operations
    "AddField",
    "RemoveField",
    "AlterField",
    "RenameField",
    # Index operations
    "AddIndex",
    "RemoveIndex",
    "RenameIndex",
    # Constraint operations
    "AddConstraint",
    "RemoveConstraint",
    # Special operations
    "SeparateDatabaseAndState",
    "RunSQL",
    "RunPython",
    # Type hints for RunPython functions
    "BaseDatabaseSchemaEditor",
    "StateModelsRegistry",
]
