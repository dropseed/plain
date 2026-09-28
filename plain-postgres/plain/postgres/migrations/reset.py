"""Replace a package's migration history with one baseline.

The baseline is the file the runtime already understands (see
`Migration.supersedes`): the package's schema at its leaf as `CreateModel`
operations, the leaf's name as adoption evidence, every deleted name so
dependencies on them still resolve. `plan_reset` builds it and every check
runs before a file is touched; the CLI writes and deletes.
"""

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from plain.postgres.fields.related import ManyToManyField, RelatedField
from plain.postgres.options import CONVERGENCE_OPTIONS

from . import operations
from .autodetector import (
    MigrationAutodetector,
    describe_changes,
    detect_model_changes,
    package_creation_operations,
)
from .exceptions import (
    BadMigrationError,
    CircularDependencyError,
    MigrationSchemaError,
)
from .loader import MigrationLoader
from .migration import Migration
from .state import ProjectState
from .utils import resolve_relation

if TYPE_CHECKING:
    from .operations.base import Operation

# What the autodetector can regenerate from model state. Anything else in the
# deleted history has an effect a baseline cannot carry.
REGENERABLE_OPERATIONS = (
    operations.CreateModel,
    operations.DeleteModel,
    operations.RenameModel,
    operations.AlterModelOptions,
    operations.AlterModelTable,
    operations.AddField,
    operations.RemoveField,
    operations.AlterField,
    operations.RenameField,
)


@dataclass
class ResetPlan:
    baseline: Migration
    migrations_dir: Path
    delete: list[Path]

    @property
    def package_label(self) -> str:
        return self.baseline.package_label

    @property
    def sentinel(self) -> str:
        assert self.baseline.supersedes is not None
        return self.baseline.supersedes


def plan_reset(
    loader: MigrationLoader, package_label: str, *, shipped_in: str = ""
) -> ResetPlan:
    """Build the baseline that would replace `package_label`'s history.

    Raises `BadMigrationError` for anything that makes the reset unsafe.
    """
    assert loader.disk_migrations is not None
    on_disk = {
        name: migration
        for (label, name), migration in loader.disk_migrations.items()
        if label == package_label
    }
    if package_label not in loader.migrated_packages or not on_disk:
        raise BadMigrationError(f"`{package_label}` has no migrations to reset.")

    leaves = loader.graph.leaf_nodes(package_label)
    if len(leaves) != 1:
        raise BadMigrationError(
            f"`{package_label}` has {len(leaves)} leaf migrations "
            f"({', '.join(name for _, name in leaves)}); a reset needs one. Give "
            "one a dependency on the other so the package ends in a single "
            "migration, then reset."
        )
    sentinel = leaves[0][1]

    previous = loader.baselines.get(package_label)
    if previous is not None and not previous.shipped_in:
        raise BadMigrationError(
            f"`{package_label}` already has a baseline ({previous.name}) that no "
            "release has shipped (`shipped_in` is empty). Superseding it would strand "
            f"every database still at {previous.supersedes}. Once that baseline has "
            "shipped everywhere, set its `shipped_in` to the version that shipped it and "
            "reset again; otherwise restore the history it replaced and reset once."
        )

    unregenerable = [
        f"{package_label}.{name}: {operation.describe()} (operation {position})"
        for name, migration in on_disk.items()
        for position, operation in _unregenerable_operations(migration.operations)
    ]
    if unregenerable:
        raise BadMigrationError(
            f"The history of `{package_label}` has operations a baseline cannot "
            "carry - a fresh database would never get their effect:\n  - "
            + "\n  - ".join(unregenerable)
            + "\nIf a fresh database can do without it, mark it `skip_on_reset=True`; "
            "if not, move its effect into a seed first, then mark it. Then reset again."
        )

    retired = set(on_disk)
    if previous is not None:
        assert previous.supersedes is not None
        retired.update(previous.retired)
        retired.add(previous.supersedes)

    # Past the leaf, and never a name a database may have recorded.
    number = (MigrationAutodetector.parse_number(sentinel) or 0) + 1
    name = f"{number:04d}_baseline"
    while name in retired:
        number += 1
        name = f"{number:04d}_baseline"

    state = loader.project_state()
    try:
        baseline_operations = package_creation_operations(state, package_label)
    except ValueError as e:
        raise BadMigrationError(
            f"The models of `{package_label}` cannot be expressed as one migration: {e}"
        ) from e
    for operation in baseline_operations:
        if isinstance(operation, operations.CreateModel):
            # Replayed history still carries option keys convergence owns now.
            operation.options = {
                key: value
                for key, value in operation.options.items()
                if key not in CONVERGENCE_OPTIONS
            }

    baseline_class = type(
        "Migration",
        (Migration,),
        {
            "operations": baseline_operations,
            "dependencies": _referenced_dependencies(loader, state, package_label),
            "supersedes": sentinel,
            "retired": tuple(sorted(retired)),
            "shipped_in": shipped_in,
        },
    )
    delete = [_source_path(migration) for migration in on_disk.values()]
    return ResetPlan(
        baseline=baseline_class(name, package_label),
        migrations_dir=delete[0].parent,
        delete=delete,
    )


def validate_reset(loader: MigrationLoader, plan: ResetPlan) -> None:
    """Prove the post-reset graph loads, renders, and matches the models.

    Runs the loader's own graph build over what the disk would hold after
    the reset - the old files gone, the baseline in their place - so
    baseline registration, dependency resolution, consistency and cycle
    checks all fire here rather than after the deletion. Then renders the
    baseline's state (an FK to a model its dependencies don't supply only
    fails on render) and asks the autodetector for what `create` would
    write: nothing, or the baseline doesn't reproduce the schema.

    Raises `BadMigrationError` with the reason.
    """
    assert loader.disk_migrations is not None
    baseline_key = (plan.package_label, plan.baseline.name)
    candidate = {
        key: migration
        for key, migration in loader.disk_migrations.items()
        if key[0] != plan.package_label
    }
    candidate[baseline_key] = plan.baseline

    try:
        validation = loader.with_migrations(candidate)
        rendered = validation.graph.make_state(
            nodes=[baseline_key], real_packages=validation.unmigrated_packages
        )
        rendered.models_registry.get_models()
    except BadMigrationError:
        raise
    except CircularDependencyError as e:
        raise BadMigrationError(
            f"The baseline for `{plan.package_label}` would close a cycle in the "
            f"migration graph: {e}. A baseline is its package's only root and "
            "depends on the earliest migration of each package its models "
            "reference; another package depends on this one before that point. "
            "Nothing in this package can break the cycle - it cannot be reset "
            "to a single root."
        ) from e
    except Exception as e:
        raise BadMigrationError(str(e)) from e

    try:
        pending = detect_model_changes(validation, package_labels={plan.package_label})
    except MigrationSchemaError as e:
        raise BadMigrationError(str(e)) from e
    if pending:
        raise BadMigrationError(
            f"The baseline for `{plan.package_label}` does not reproduce its "
            "models; `create` would still write:\n  "
            + "\n  ".join(describe_changes(pending))
        )


def _unregenerable_operations(
    ops: Sequence[Operation], *, database_only: bool = False
) -> list[tuple[int, Operation]]:
    """(position, operation) for each effect the baseline cannot carry.

    The baseline is regenerated from project state, so an operation counts
    only if it also moves state. Inside `SeparateDatabaseAndState`, the
    database side does not - every operation there is unregenerable unless
    marked - while the state side is ordinary.
    """
    found: list[tuple[int, Operation]] = []
    for position, operation in enumerate(ops):
        if isinstance(operation, operations.SeparateDatabaseAndState):
            nested = _unregenerable_operations(
                operation.database_operations, database_only=True
            ) + _unregenerable_operations(operation.state_operations)
            found.extend((position, op) for _, op in nested)
        elif operation.skip_on_reset:
            continue
        elif database_only or not isinstance(operation, REGENERABLE_OPERATIONS):
            found.append((position, operation))
    return found


def _referenced_dependencies(
    loader: MigrationLoader, state: ProjectState, package_label: str
) -> list[tuple[str, str]]:
    """One dependency per other package the baseline's models reference.

    For each, the earliest migration of that package at which every model
    referenced exists under its current name - enough for a fresh database
    to render the baseline, and nothing more: every extra edge is one more
    way for a reset to close a cycle.
    """
    referenced: dict[str, set[tuple[str, str]]] = {}
    for (label, model_name), model_state in state.models.items():
        if label != package_label:
            continue
        for model_field in model_state.fields.values():
            if not isinstance(model_field, RelatedField):
                continue
            targets = [model_field.remote_field.model_ref]
            if isinstance(model_field, ManyToManyField) and isinstance(
                model_field.remote_field.through_ref, str
            ):
                targets.append(model_field.remote_field.through_ref)
            for target in targets:
                other = resolve_relation(target, label, model_name)
                if other[0] != package_label:
                    referenced.setdefault(other[0], set()).add(other)
        for base in model_state.bases:
            if isinstance(base, str) and "." in base:
                other = resolve_relation(base)
                if other[0] != package_label:
                    referenced.setdefault(other[0], set()).add(other)

    dependencies: list[tuple[str, str]] = []
    for other_label in sorted(referenced):
        if other_label in loader.unmigrated_packages:
            continue
        needed = referenced[other_label]
        # One forward replay of that package's history, checked after each
        # of its own nodes.
        replayed = ProjectState(real_packages=loader.unmigrated_packages)
        for node in _plan_for_package(loader, other_label):
            migration = loader.graph.nodes[node]
            assert migration is not None
            replayed = migration.mutate_state(replayed, preserve=False)
            if node[0] == other_label and needed <= set(replayed.models):
                dependencies.append(node)
                break
        else:
            raise BadMigrationError(
                f"`{package_label}` references "
                f"{', '.join(sorted(name for _, name in needed))} in "
                f"`{other_label}`, which no migration of `{other_label}` creates."
            )
    return dependencies


def _plan_for_package(
    loader: MigrationLoader, package_label: str
) -> list[tuple[str, str]]:
    """Every node the package's leaves need, in application order."""
    ordered: list[tuple[str, str]] = []
    for leaf in loader.graph.leaf_nodes(package_label):
        for node in loader.graph.forwards_plan(leaf):
            if node not in ordered:
                ordered.append(node)
    return ordered


def _source_path(migration: Migration) -> Path:
    module = sys.modules[type(migration).__module__]
    assert module.__file__ is not None
    return Path(module.__file__)
