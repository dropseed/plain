import re

from plain.models.migrations.utils import get_migration_name_timestamp
from plain.models.transaction import atomic


class Migration:
    """
    The base class for all migrations.

    Migration files will import this from plain.models.migrations.Migration
    and subclass it as a class called Migration. It will have one or more
    of the following attributes:

     - operations: A list of Operation instances, probably from
       plain.models.migrations.operations
     - dependencies: A list of tuples of (app_path, migration_name)
     - replaces: A list of migration_names

    Note that all migrations come out of migrations and into the Loader or
    Graph as instances, having been initialized with their app label and name.
    """

    # Operations to apply during this migration, in order.
    operations = []

    # Other migrations that should be run before this migration.
    # Should be a list of (app, migration_name).
    dependencies = []

    # Migration names in this app that this migration replaces. If this is
    # non-empty, this migration will only be applied if all these migrations
    # are not applied.
    replaces = []

    # Is this an initial migration? Initial migrations are skipped on
    # --fake-initial if the table or fields already exist. If None, check if
    # the migration has any dependencies to determine if there are dependencies
    # to tell if db introspection needs to be done. If True, always perform
    # introspection. If False, never perform introspection.
    initial = None

    # Whether to wrap the whole migration in a transaction. Only has an effect
    # on database backends which support transactional DDL.
    atomic = True

    def __init__(self, name, package_label):
        self.name = name
        self.package_label = package_label
        # Copy dependencies & other attrs as we might mutate them at runtime
        self.operations = list(self.__class__.operations)
        self.dependencies = list(self.__class__.dependencies)
        self.replaces = list(self.__class__.replaces)

    def __eq__(self, other):
        return (
            isinstance(other, Migration)
            and self.name == other.name
            and self.package_label == other.package_label
        )

    def __repr__(self):
        return f"<Migration {self.package_label}.{self.name}>"

    def __str__(self):
        return f"{self.package_label}.{self.name}"

    def __hash__(self):
        return hash(f"{self.package_label}.{self.name}")

    def mutate_state(self, project_state, preserve=True):
        """
        Take a ProjectState and return a new one with the migration's
        operations applied to it. Preserve the original object state by
        default and return a mutated state from a copy.
        """
        new_state = project_state
        if preserve:
            new_state = project_state.clone()

        for operation in self.operations:
            operation.state_forwards(self.package_label, new_state)
        return new_state

    def apply(self, project_state, schema_editor, collect_sql=False):
        """
        Take a project_state representing all migrations prior to this one
        and a schema_editor for a live database and apply the migration
        in a forwards order.

        Return the resulting project state for efficient reuse by following
        Migrations.
        """
        for operation in self.operations:
            # If this operation cannot be represented as SQL, place a comment
            # there instead
            if collect_sql:
                schema_editor.collected_sql.append("--")
                schema_editor.collected_sql.append(f"-- {operation.describe()}")
                schema_editor.collected_sql.append("--")
                if not operation.reduces_to_sql:
                    schema_editor.collected_sql.append(
                        "-- THIS OPERATION CANNOT BE WRITTEN AS SQL"
                    )
                    continue
                collected_sql_before = len(schema_editor.collected_sql)
            # Save the state before the operation has run
            old_state = project_state.clone()
            operation.state_forwards(self.package_label, project_state)
            # Run the operation
            atomic_operation = operation.atomic or (
                self.atomic and operation.atomic is not False
            )
            if not schema_editor.atomic_migration and atomic_operation:
                # Force a transaction on a non-transactional-DDL backend or an
                # atomic operation inside a non-atomic migration.
                with atomic():
                    operation.database_forwards(
                        self.package_label, schema_editor, old_state, project_state
                    )
            else:
                # Normal behaviour
                operation.database_forwards(
                    self.package_label, schema_editor, old_state, project_state
                )
            if collect_sql and collected_sql_before == len(schema_editor.collected_sql):
                schema_editor.collected_sql.append("-- (no-op)")
        return project_state

    def suggest_name(self):
        """
        Suggest a name for the operations this migration might represent. Names
        are not guaranteed to be unique, but put some effort into the fallback
        name to avoid VCS conflicts if possible.
        """
        if self.initial:
            return "initial"

        raw_fragments = [op.migration_name_fragment for op in self.operations]
        fragments = [re.sub(r"\W+", "_", name) for name in raw_fragments if name]

        if not fragments or len(fragments) != len(self.operations):
            return f"auto_{get_migration_name_timestamp()}"

        name = fragments[0]
        for fragment in fragments[1:]:
            new_name = f"{name}_{fragment}"
            if len(new_name) > 52:
                name = f"{name}_and_more"
                break
            name = new_name
        return name


class SettingsTuple(tuple):
    """
    Subclass of tuple so Plain can tell this was originally a settings
    dependency when it reads the migration file.
    """

    def __new__(cls, value, setting):
        self = tuple.__new__(cls, value)
        self.setting = setting
        return self


def settings_dependency(value):
    """Turn a setting value into a dependency."""
    return SettingsTuple((value.split(".", 1)[0], "__first__"), value)
