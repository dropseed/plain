import functools
import re
from graphlib import TopologicalSorter
from itertools import chain

from plain import models
from plain.models.migrations import operations
from plain.models.migrations.migration import Migration
from plain.models.migrations.operations.models import AlterModelOptions
from plain.models.migrations.optimizer import MigrationOptimizer
from plain.models.migrations.questioner import MigrationQuestioner
from plain.models.migrations.utils import (
    COMPILED_REGEX_TYPE,
    RegexObject,
    resolve_relation,
)
from plain.runtime import settings


class MigrationAutodetector:
    """
    Take a pair of ProjectStates and compare them to see what the first would
    need doing to make it match the second (the second usually being the
    project's current state).

    Note that this naturally operates on entire projects at a time,
    as it's likely that changes interact (for example, you can't
    add a ForeignKey without having a migration to add the table it
    depends on first). A user interface may offer single-app usage
    if it wishes, with the caveat that it may not always be possible.
    """

    def __init__(self, from_state, to_state, questioner=None):
        self.from_state = from_state
        self.to_state = to_state
        self.questioner = questioner or MigrationQuestioner()
        self.existing_packages = {app for app, model in from_state.models}

    def changes(
        self, graph, trim_to_packages=None, convert_packages=None, migration_name=None
    ):
        """
        Main entry point to produce a list of applicable changes.
        Take a graph to base names on and an optional set of packages
        to try and restrict to (restriction is not guaranteed)
        """
        changes = self._detect_changes(convert_packages, graph)
        changes = self.arrange_for_graph(changes, graph, migration_name)
        if trim_to_packages:
            changes = self._trim_to_packages(changes, trim_to_packages)
        return changes

    def deep_deconstruct(self, obj):
        """
        Recursive deconstruction for a field and its arguments.
        Used for full comparison for rename/alter; sometimes a single-level
        deconstruction will not compare correctly.
        """
        if isinstance(obj, list):
            return [self.deep_deconstruct(value) for value in obj]
        elif isinstance(obj, tuple):
            return tuple(self.deep_deconstruct(value) for value in obj)
        elif isinstance(obj, dict):
            return {key: self.deep_deconstruct(value) for key, value in obj.items()}
        elif isinstance(obj, functools.partial):
            return (
                obj.func,
                self.deep_deconstruct(obj.args),
                self.deep_deconstruct(obj.keywords),
            )
        elif isinstance(obj, COMPILED_REGEX_TYPE):
            return RegexObject(obj)
        elif isinstance(obj, type):
            # If this is a type that implements 'deconstruct' as an instance method,
            # avoid treating this as being deconstructible itself - see #22951
            return obj
        elif hasattr(obj, "deconstruct"):
            deconstructed = obj.deconstruct()
            if isinstance(obj, models.Field):
                # we have a field which also returns a name
                deconstructed = deconstructed[1:]
            path, args, kwargs = deconstructed
            return (
                path,
                [self.deep_deconstruct(value) for value in args],
                {key: self.deep_deconstruct(value) for key, value in kwargs.items()},
            )
        else:
            return obj

    def only_relation_agnostic_fields(self, fields):
        """
        Return a definition of the fields that ignores field names and
        what related fields actually relate to. Used for detecting renames (as
        the related fields change during renames).
        """
        fields_def = []
        for name, field in sorted(fields.items()):
            deconstruction = self.deep_deconstruct(field)
            if field.remote_field and field.remote_field.model:
                deconstruction[2].pop("to", None)
            fields_def.append(deconstruction)
        return fields_def

    def _detect_changes(self, convert_packages=None, graph=None):
        """
        Return a dict of migration plans which will achieve the
        change from from_state to to_state. The dict has app labels
        as keys and a list of migrations as values.

        The resulting migrations aren't specially named, but the names
        do matter for dependencies inside the set.

        convert_packages is the list of packages to convert to use migrations
        (i.e. to make initial migrations for, in the usual case)

        graph is an optional argument that, if provided, can help improve
        dependency generation and avoid potential circular dependencies.
        """
        # The first phase is generating all the operations for each app
        # and gathering them into a big per-app list.
        # Then go through that list, order it, and split into migrations to
        # resolve dependencies caused by M2Ms and FKs.
        self.generated_operations = {}
        self.altered_indexes = {}
        self.altered_constraints = {}
        self.renamed_fields = {}

        # Prepare some old/new state and model lists, ignoring unmigrated packages.
        self.old_model_keys = set()
        self.old_unmanaged_keys = set()
        self.new_model_keys = set()
        self.new_unmanaged_keys = set()
        for (package_label, model_name), model_state in self.from_state.models.items():
            if not model_state.options.get("managed", True):
                self.old_unmanaged_keys.add((package_label, model_name))
            elif package_label not in self.from_state.real_packages:
                self.old_model_keys.add((package_label, model_name))

        for (package_label, model_name), model_state in self.to_state.models.items():
            if not model_state.options.get("managed", True):
                self.new_unmanaged_keys.add((package_label, model_name))
            elif package_label not in self.from_state.real_packages or (
                convert_packages and package_label in convert_packages
            ):
                self.new_model_keys.add((package_label, model_name))

        self.from_state.resolve_fields_and_relations()
        self.to_state.resolve_fields_and_relations()

        # Renames have to come first
        self.generate_renamed_models()

        # Prepare lists of fields and generate through model map
        self._prepare_field_lists()
        self._generate_through_model_map()

        # Generate non-rename model operations
        self.generate_deleted_models()
        self.generate_created_models()
        self.generate_altered_options()
        self.generate_altered_managers()
        self.generate_altered_db_table_comment()

        # Create the renamed fields and store them in self.renamed_fields.
        # They are used by create_altered_indexes(), generate_altered_fields(),
        # generate_removed_altered_index/unique_together(), and
        # generate_altered_index/unique_together().
        self.create_renamed_fields()
        # Create the altered indexes and store them in self.altered_indexes.
        # This avoids the same computation in generate_removed_indexes()
        # and generate_added_indexes().
        self.create_altered_indexes()
        self.create_altered_constraints()
        # Generate index removal operations before field is removed
        self.generate_removed_constraints()
        self.generate_removed_indexes()
        # Generate field renaming operations.
        self.generate_renamed_fields()
        self.generate_renamed_indexes()
        # Generate removal of foo together.
        self.generate_removed_altered_unique_together()
        # Generate field operations.
        self.generate_removed_fields()
        self.generate_added_fields()
        self.generate_altered_fields()
        self.generate_altered_order_with_respect_to()
        self.generate_altered_unique_together()
        self.generate_added_indexes()
        self.generate_added_constraints()
        self.generate_altered_db_table()

        self._sort_migrations()
        self._build_migration_list(graph)
        self._optimize_migrations()

        return self.migrations

    def _prepare_field_lists(self):
        """
        Prepare field lists and a list of the fields that used through models
        in the old state so dependencies can be made from the through model
        deletion to the field that uses it.
        """
        self.kept_model_keys = self.old_model_keys & self.new_model_keys
        self.kept_unmanaged_keys = self.old_unmanaged_keys & self.new_unmanaged_keys
        self.through_users = {}
        self.old_field_keys = {
            (package_label, model_name, field_name)
            for package_label, model_name in self.kept_model_keys
            for field_name in self.from_state.models[
                package_label,
                self.renamed_models.get((package_label, model_name), model_name),
            ].fields
        }
        self.new_field_keys = {
            (package_label, model_name, field_name)
            for package_label, model_name in self.kept_model_keys
            for field_name in self.to_state.models[package_label, model_name].fields
        }

    def _generate_through_model_map(self):
        """Through model map generation."""
        for package_label, model_name in sorted(self.old_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            for field_name, field in old_model_state.fields.items():
                if hasattr(field, "remote_field") and getattr(
                    field.remote_field, "through", None
                ):
                    through_key = resolve_relation(
                        field.remote_field.through, package_label, model_name
                    )
                    self.through_users[through_key] = (
                        package_label,
                        old_model_name,
                        field_name,
                    )

    @staticmethod
    def _resolve_dependency(dependency):
        """
        Return the resolved dependency and a boolean denoting whether or not
        it was swappable.
        """
        if dependency[0] != "__setting__":
            return dependency, False
        resolved_package_label, resolved_object_name = getattr(
            settings, dependency[1]
        ).split(".")
        return (resolved_package_label, resolved_object_name.lower()) + dependency[
            2:
        ], True

    def _build_migration_list(self, graph=None):
        """
        Chop the lists of operations up into migrations with dependencies on
        each other. Do this by going through an app's list of operations until
        one is found that has an outgoing dependency that isn't in another
        app's migration yet (hasn't been chopped off its list). Then chop off
        the operations before it into a migration and move onto the next app.
        If the loops completes without doing anything, there's a circular
        dependency (which _should_ be impossible as the operations are
        all split at this point so they can't depend and be depended on).
        """
        self.migrations = {}
        num_ops = sum(len(x) for x in self.generated_operations.values())
        chop_mode = False
        while num_ops:
            # On every iteration, we step through all the packages and see if there
            # is a completed set of operations.
            # If we find that a subset of the operations are complete we can
            # try to chop it off from the rest and continue, but we only
            # do this if we've already been through the list once before
            # without any chopping and nothing has changed.
            for package_label in sorted(self.generated_operations):
                chopped = []
                dependencies = set()
                for operation in list(self.generated_operations[package_label]):
                    deps_satisfied = True
                    operation_dependencies = set()
                    for dep in operation._auto_deps:
                        # Temporarily resolve the swappable dependency to
                        # prevent circular references. While keeping the
                        # dependency checks on the resolved model, add the
                        # swappable dependencies.
                        original_dep = dep
                        dep, is_swappable_dep = self._resolve_dependency(dep)
                        if dep[0] != package_label:
                            # External app dependency. See if it's not yet
                            # satisfied.
                            for other_operation in self.generated_operations.get(
                                dep[0], []
                            ):
                                if self.check_dependency(other_operation, dep):
                                    deps_satisfied = False
                                    break
                            if not deps_satisfied:
                                break
                            else:
                                if is_swappable_dep:
                                    operation_dependencies.add(
                                        (original_dep[0], original_dep[1])
                                    )
                                elif dep[0] in self.migrations:
                                    operation_dependencies.add(
                                        (dep[0], self.migrations[dep[0]][-1].name)
                                    )
                                else:
                                    # If we can't find the other app, we add a
                                    # first/last dependency, but only if we've
                                    # already been through once and checked
                                    # everything.
                                    if chop_mode:
                                        # If the app already exists, we add a
                                        # dependency on the last migration, as
                                        # we don't know which migration
                                        # contains the target field. If it's
                                        # not yet migrated or has no
                                        # migrations, we use __first__.
                                        if graph and graph.leaf_nodes(dep[0]):
                                            operation_dependencies.add(
                                                graph.leaf_nodes(dep[0])[0]
                                            )
                                        else:
                                            operation_dependencies.add(
                                                (dep[0], "__first__")
                                            )
                                    else:
                                        deps_satisfied = False
                    if deps_satisfied:
                        chopped.append(operation)
                        dependencies.update(operation_dependencies)
                        del self.generated_operations[package_label][0]
                    else:
                        break
                # Make a migration! Well, only if there's stuff to put in it
                if dependencies or chopped:
                    if not self.generated_operations[package_label] or chop_mode:
                        subclass = type(
                            "Migration",
                            (Migration,),
                            {"operations": [], "dependencies": []},
                        )
                        instance = subclass(
                            "auto_%i"
                            % (len(self.migrations.get(package_label, [])) + 1),
                            package_label,
                        )
                        instance.dependencies = list(dependencies)
                        instance.operations = chopped
                        instance.initial = package_label not in self.existing_packages
                        self.migrations.setdefault(package_label, []).append(instance)
                        chop_mode = False
                    else:
                        self.generated_operations[package_label] = (
                            chopped + self.generated_operations[package_label]
                        )
            new_num_ops = sum(len(x) for x in self.generated_operations.values())
            if new_num_ops == num_ops:
                if not chop_mode:
                    chop_mode = True
                else:
                    raise ValueError(
                        "Cannot resolve operation dependencies: %r"
                        % self.generated_operations
                    )
            num_ops = new_num_ops

    def _sort_migrations(self):
        """
        Reorder to make things possible. Reordering may be needed so FKs work
        nicely inside the same app.
        """
        for package_label, ops in sorted(self.generated_operations.items()):
            ts = TopologicalSorter()
            for op in ops:
                ts.add(op)
                for dep in op._auto_deps:
                    # Resolve intra-app dependencies to handle circular
                    # references involving a swappable model.
                    dep = self._resolve_dependency(dep)[0]
                    if dep[0] != package_label:
                        continue
                    ts.add(op, *(x for x in ops if self.check_dependency(x, dep)))
            self.generated_operations[package_label] = list(ts.static_order())

    def _optimize_migrations(self):
        # Add in internal dependencies among the migrations
        for package_label, migrations in self.migrations.items():
            for m1, m2 in zip(migrations, migrations[1:]):
                m2.dependencies.append((package_label, m1.name))

        # De-dupe dependencies
        for migrations in self.migrations.values():
            for migration in migrations:
                migration.dependencies = list(set(migration.dependencies))

        # Optimize migrations
        for package_label, migrations in self.migrations.items():
            for migration in migrations:
                migration.operations = MigrationOptimizer().optimize(
                    migration.operations, package_label
                )

    def check_dependency(self, operation, dependency):
        """
        Return True if the given operation depends on the given dependency,
        False otherwise.
        """
        # Created model
        if dependency[2] is None and dependency[3] is True:
            return (
                isinstance(operation, operations.CreateModel)
                and operation.name_lower == dependency[1].lower()
            )
        # Created field
        elif dependency[2] is not None and dependency[3] is True:
            return (
                isinstance(operation, operations.CreateModel)
                and operation.name_lower == dependency[1].lower()
                and any(dependency[2] == x for x, y in operation.fields)
            ) or (
                isinstance(operation, operations.AddField)
                and operation.model_name_lower == dependency[1].lower()
                and operation.name_lower == dependency[2].lower()
            )
        # Removed field
        elif dependency[2] is not None and dependency[3] is False:
            return (
                isinstance(operation, operations.RemoveField)
                and operation.model_name_lower == dependency[1].lower()
                and operation.name_lower == dependency[2].lower()
            )
        # Removed model
        elif dependency[2] is None and dependency[3] is False:
            return (
                isinstance(operation, operations.DeleteModel)
                and operation.name_lower == dependency[1].lower()
            )
        # Field being altered
        elif dependency[2] is not None and dependency[3] == "alter":
            return (
                isinstance(operation, operations.AlterField)
                and operation.model_name_lower == dependency[1].lower()
                and operation.name_lower == dependency[2].lower()
            )
        # order_with_respect_to being unset for a field
        elif dependency[2] is not None and dependency[3] == "order_wrt_unset":
            return (
                isinstance(operation, operations.AlterOrderWithRespectTo)
                and operation.name_lower == dependency[1].lower()
                and (operation.order_with_respect_to or "").lower()
                != dependency[2].lower()
            )
        # Field is removed and part of an index/unique_together
        elif dependency[2] is not None and dependency[3] == "foo_together_change":
            return (
                isinstance(
                    operation,
                    operations.AlterUniqueTogether,
                )
                and operation.name_lower == dependency[1].lower()
            )
        # Unknown dependency. Raise an error.
        else:
            raise ValueError(f"Can't handle dependency {dependency!r}")

    def add_operation(
        self, package_label, operation, dependencies=None, beginning=False
    ):
        # Dependencies are
        # (package_label, model_name, field_name, create/delete as True/False)
        operation._auto_deps = dependencies or []
        if beginning:
            self.generated_operations.setdefault(package_label, []).insert(0, operation)
        else:
            self.generated_operations.setdefault(package_label, []).append(operation)

    def swappable_first_key(self, item):
        """
        Place potential swappable models first in lists of created models (only
        real way to solve #22783).
        """
        try:
            model_state = self.to_state.models[item]
            base_names = {
                base if isinstance(base, str) else base.__name__
                for base in model_state.bases
            }
            string_version = f"{item[0]}.{item[1]}"
            if (
                model_state.options.get("swappable")
                or "BaseUser" in base_names
                or "AbstractBaseUser" in base_names
                or settings.AUTH_USER_MODEL.lower() == string_version.lower()
            ):
                return ("___" + item[0], "___" + item[1])
        except LookupError:
            pass
        return item

    def generate_renamed_models(self):
        """
        Find any renamed models, generate the operations for them, and remove
        the old entry from the model lists. Must be run before other
        model-level generation.
        """
        self.renamed_models = {}
        self.renamed_models_rel = {}
        added_models = self.new_model_keys - self.old_model_keys
        for package_label, model_name in sorted(added_models):
            model_state = self.to_state.models[package_label, model_name]
            model_fields_def = self.only_relation_agnostic_fields(model_state.fields)

            removed_models = self.old_model_keys - self.new_model_keys
            for rem_package_label, rem_model_name in removed_models:
                if rem_package_label == package_label:
                    rem_model_state = self.from_state.models[
                        rem_package_label, rem_model_name
                    ]
                    rem_model_fields_def = self.only_relation_agnostic_fields(
                        rem_model_state.fields
                    )
                    if model_fields_def == rem_model_fields_def:
                        if self.questioner.ask_rename_model(
                            rem_model_state, model_state
                        ):
                            dependencies = []
                            fields = list(model_state.fields.values()) + [
                                field.remote_field
                                for relations in self.to_state.relations[
                                    package_label, model_name
                                ].values()
                                for field in relations.values()
                            ]
                            for field in fields:
                                if field.is_relation:
                                    dependencies.extend(
                                        self._get_dependencies_for_foreign_key(
                                            package_label,
                                            model_name,
                                            field,
                                            self.to_state,
                                        )
                                    )
                            self.add_operation(
                                package_label,
                                operations.RenameModel(
                                    old_name=rem_model_state.name,
                                    new_name=model_state.name,
                                ),
                                dependencies=dependencies,
                            )
                            self.renamed_models[
                                package_label, model_name
                            ] = rem_model_name
                            renamed_models_rel_key = "{}.{}".format(
                                rem_model_state.package_label,
                                rem_model_state.name_lower,
                            )
                            self.renamed_models_rel[
                                renamed_models_rel_key
                            ] = f"{model_state.package_label}.{model_state.name_lower}"
                            self.old_model_keys.remove(
                                (rem_package_label, rem_model_name)
                            )
                            self.old_model_keys.add((package_label, model_name))
                            break

    def generate_created_models(self):
        """
        Find all new models (both managed and unmanaged) and make create
        operations for them as well as separate operations to create any
        foreign key or M2M relationships (these are optimized later, if
        possible).

        Defer any model options that refer to collections of fields that might
        be deferred (e.g. unique_together).
        """
        old_keys = self.old_model_keys | self.old_unmanaged_keys
        added_models = self.new_model_keys - old_keys
        added_unmanaged_models = self.new_unmanaged_keys - old_keys
        all_added_models = chain(
            sorted(added_models, key=self.swappable_first_key, reverse=True),
            sorted(added_unmanaged_models, key=self.swappable_first_key, reverse=True),
        )
        for package_label, model_name in all_added_models:
            model_state = self.to_state.models[package_label, model_name]
            # Gather related fields
            related_fields = {}
            primary_key_rel = None
            for field_name, field in model_state.fields.items():
                if field.remote_field:
                    if field.remote_field.model:
                        if field.primary_key:
                            primary_key_rel = field.remote_field.model
                        elif not field.remote_field.parent_link:
                            related_fields[field_name] = field
                    if getattr(field.remote_field, "through", None):
                        related_fields[field_name] = field

            # Are there indexes/unique_together to defer?
            indexes = model_state.options.pop("indexes")
            constraints = model_state.options.pop("constraints")
            unique_together = model_state.options.pop("unique_together", None)
            order_with_respect_to = model_state.options.pop(
                "order_with_respect_to", None
            )
            # Depend on the deletion of any possible proxy version of us
            dependencies = [
                (package_label, model_name, None, False),
            ]
            # Depend on all bases
            for base in model_state.bases:
                if isinstance(base, str) and "." in base:
                    base_package_label, base_name = base.split(".", 1)
                    dependencies.append((base_package_label, base_name, None, True))
                    # Depend on the removal of base fields if the new model has
                    # a field with the same name.
                    old_base_model_state = self.from_state.models.get(
                        (base_package_label, base_name)
                    )
                    new_base_model_state = self.to_state.models.get(
                        (base_package_label, base_name)
                    )
                    if old_base_model_state and new_base_model_state:
                        removed_base_fields = (
                            set(old_base_model_state.fields)
                            .difference(
                                new_base_model_state.fields,
                            )
                            .intersection(model_state.fields)
                        )
                        for removed_base_field in removed_base_fields:
                            dependencies.append(
                                (
                                    base_package_label,
                                    base_name,
                                    removed_base_field,
                                    False,
                                )
                            )
            # Depend on the other end of the primary key if it's a relation
            if primary_key_rel:
                dependencies.append(
                    resolve_relation(
                        primary_key_rel,
                        package_label,
                        model_name,
                    )
                    + (None, True)
                )
            # Generate creation operation
            self.add_operation(
                package_label,
                operations.CreateModel(
                    name=model_state.name,
                    fields=[
                        d
                        for d in model_state.fields.items()
                        if d[0] not in related_fields
                    ],
                    options=model_state.options,
                    bases=model_state.bases,
                    managers=model_state.managers,
                ),
                dependencies=dependencies,
                beginning=True,
            )

            # Don't add operations which modify the database for unmanaged models
            if not model_state.options.get("managed", True):
                continue

            # Generate operations for each related field
            for name, field in sorted(related_fields.items()):
                dependencies = self._get_dependencies_for_foreign_key(
                    package_label,
                    model_name,
                    field,
                    self.to_state,
                )
                # Depend on our own model being created
                dependencies.append((package_label, model_name, None, True))
                # Make operation
                self.add_operation(
                    package_label,
                    operations.AddField(
                        model_name=model_name,
                        name=name,
                        field=field,
                    ),
                    dependencies=list(set(dependencies)),
                )
            # Generate other opns
            if order_with_respect_to:
                self.add_operation(
                    package_label,
                    operations.AlterOrderWithRespectTo(
                        name=model_name,
                        order_with_respect_to=order_with_respect_to,
                    ),
                    dependencies=[
                        (package_label, model_name, order_with_respect_to, True),
                        (package_label, model_name, None, True),
                    ],
                )
            related_dependencies = [
                (package_label, model_name, name, True)
                for name in sorted(related_fields)
            ]
            related_dependencies.append((package_label, model_name, None, True))
            for index in indexes:
                self.add_operation(
                    package_label,
                    operations.AddIndex(
                        model_name=model_name,
                        index=index,
                    ),
                    dependencies=related_dependencies,
                )
            for constraint in constraints:
                self.add_operation(
                    package_label,
                    operations.AddConstraint(
                        model_name=model_name,
                        constraint=constraint,
                    ),
                    dependencies=related_dependencies,
                )
            if unique_together:
                self.add_operation(
                    package_label,
                    operations.AlterUniqueTogether(
                        name=model_name,
                        unique_together=unique_together,
                    ),
                    dependencies=related_dependencies,
                )

    def generate_deleted_models(self):
        """
        Find all deleted models (managed and unmanaged) and make delete
        operations for them as well as separate operations to delete any
        foreign key or M2M relationships (these are optimized later, if
        possible).

        Also bring forward removal of any model options that refer to
        collections of fields - the inverse of generate_created_models().
        """
        new_keys = self.new_model_keys | self.new_unmanaged_keys
        deleted_models = self.old_model_keys - new_keys
        deleted_unmanaged_models = self.old_unmanaged_keys - new_keys
        all_deleted_models = chain(
            sorted(deleted_models), sorted(deleted_unmanaged_models)
        )
        for package_label, model_name in all_deleted_models:
            model_state = self.from_state.models[package_label, model_name]
            # Gather related fields
            related_fields = {}
            for field_name, field in model_state.fields.items():
                if field.remote_field:
                    if field.remote_field.model:
                        related_fields[field_name] = field
                    if getattr(field.remote_field, "through", None):
                        related_fields[field_name] = field
            # Generate option removal first
            unique_together = model_state.options.pop("unique_together", None)
            if unique_together:
                self.add_operation(
                    package_label,
                    operations.AlterUniqueTogether(
                        name=model_name,
                        unique_together=None,
                    ),
                )
            # Then remove each related field
            for name in sorted(related_fields):
                self.add_operation(
                    package_label,
                    operations.RemoveField(
                        model_name=model_name,
                        name=name,
                    ),
                )
            # Finally, remove the model.
            # This depends on both the removal/alteration of all incoming fields
            # and the removal of all its own related fields, and if it's
            # a through model the field that references it.
            dependencies = []
            relations = self.from_state.relations
            for (
                related_object_package_label,
                object_name,
            ), relation_related_fields in relations[package_label, model_name].items():
                for field_name, field in relation_related_fields.items():
                    dependencies.append(
                        (related_object_package_label, object_name, field_name, False),
                    )
                    if not field.many_to_many:
                        dependencies.append(
                            (
                                related_object_package_label,
                                object_name,
                                field_name,
                                "alter",
                            ),
                        )

            for name in sorted(related_fields):
                dependencies.append((package_label, model_name, name, False))
            # We're referenced in another field's through=
            through_user = self.through_users.get(
                (package_label, model_state.name_lower)
            )
            if through_user:
                dependencies.append(
                    (through_user[0], through_user[1], through_user[2], False)
                )
            # Finally, make the operation, deduping any dependencies
            self.add_operation(
                package_label,
                operations.DeleteModel(
                    name=model_state.name,
                ),
                dependencies=list(set(dependencies)),
            )

    def create_renamed_fields(self):
        """Work out renamed fields."""
        self.renamed_operations = []
        old_field_keys = self.old_field_keys.copy()
        for package_label, model_name, field_name in sorted(
            self.new_field_keys - old_field_keys
        ):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]
            field = new_model_state.get_field(field_name)
            # Scan to see if this is actually a rename!
            field_dec = self.deep_deconstruct(field)
            for rem_package_label, rem_model_name, rem_field_name in sorted(
                old_field_keys - self.new_field_keys
            ):
                if rem_package_label == package_label and rem_model_name == model_name:
                    old_field = old_model_state.get_field(rem_field_name)
                    old_field_dec = self.deep_deconstruct(old_field)
                    if (
                        field.remote_field
                        and field.remote_field.model
                        and "to" in old_field_dec[2]
                    ):
                        old_rel_to = old_field_dec[2]["to"]
                        if old_rel_to in self.renamed_models_rel:
                            old_field_dec[2]["to"] = self.renamed_models_rel[old_rel_to]
                    old_field.set_attributes_from_name(rem_field_name)
                    old_db_column = old_field.get_attname_column()[1]
                    if old_field_dec == field_dec or (
                        # Was the field renamed and db_column equal to the
                        # old field's column added?
                        old_field_dec[0:2] == field_dec[0:2]
                        and dict(old_field_dec[2], db_column=old_db_column)
                        == field_dec[2]
                    ):
                        if self.questioner.ask_rename(
                            model_name, rem_field_name, field_name, field
                        ):
                            self.renamed_operations.append(
                                (
                                    rem_package_label,
                                    rem_model_name,
                                    old_field.db_column,
                                    rem_field_name,
                                    package_label,
                                    model_name,
                                    field,
                                    field_name,
                                )
                            )
                            old_field_keys.remove(
                                (rem_package_label, rem_model_name, rem_field_name)
                            )
                            old_field_keys.add((package_label, model_name, field_name))
                            self.renamed_fields[
                                package_label, model_name, field_name
                            ] = rem_field_name
                            break

    def generate_renamed_fields(self):
        """Generate RenameField operations."""
        for (
            rem_package_label,
            rem_model_name,
            rem_db_column,
            rem_field_name,
            package_label,
            model_name,
            field,
            field_name,
        ) in self.renamed_operations:
            # A db_column mismatch requires a prior noop AlterField for the
            # subsequent RenameField to be a noop on attempts at preserving the
            # old name.
            if rem_db_column != field.db_column:
                altered_field = field.clone()
                altered_field.name = rem_field_name
                self.add_operation(
                    package_label,
                    operations.AlterField(
                        model_name=model_name,
                        name=rem_field_name,
                        field=altered_field,
                    ),
                )
            self.add_operation(
                package_label,
                operations.RenameField(
                    model_name=model_name,
                    old_name=rem_field_name,
                    new_name=field_name,
                ),
            )
            self.old_field_keys.remove(
                (rem_package_label, rem_model_name, rem_field_name)
            )
            self.old_field_keys.add((package_label, model_name, field_name))

    def generate_added_fields(self):
        """Make AddField operations."""
        for package_label, model_name, field_name in sorted(
            self.new_field_keys - self.old_field_keys
        ):
            self._generate_added_field(package_label, model_name, field_name)

    def _generate_added_field(self, package_label, model_name, field_name):
        field = self.to_state.models[package_label, model_name].get_field(field_name)
        # Adding a field always depends at least on its removal.
        dependencies = [(package_label, model_name, field_name, False)]
        # Fields that are foreignkeys/m2ms depend on stuff.
        if field.remote_field and field.remote_field.model:
            dependencies.extend(
                self._get_dependencies_for_foreign_key(
                    package_label,
                    model_name,
                    field,
                    self.to_state,
                )
            )
        # You can't just add NOT NULL fields with no default or fields
        # which don't allow empty strings as default.
        time_fields = (models.DateField, models.DateTimeField, models.TimeField)
        preserve_default = (
            field.null
            or field.has_default()
            or field.many_to_many
            or (field.blank and field.empty_strings_allowed)
            or (isinstance(field, time_fields) and field.auto_now)
        )
        if not preserve_default:
            field = field.clone()
            if isinstance(field, time_fields) and field.auto_now_add:
                field.default = self.questioner.ask_auto_now_add_addition(
                    field_name, model_name
                )
            else:
                field.default = self.questioner.ask_not_null_addition(
                    field_name, model_name
                )
        if (
            field.unique
            and field.default is not models.NOT_PROVIDED
            and callable(field.default)
        ):
            self.questioner.ask_unique_callable_default_addition(field_name, model_name)
        self.add_operation(
            package_label,
            operations.AddField(
                model_name=model_name,
                name=field_name,
                field=field,
                preserve_default=preserve_default,
            ),
            dependencies=dependencies,
        )

    def generate_removed_fields(self):
        """Make RemoveField operations."""
        for package_label, model_name, field_name in sorted(
            self.old_field_keys - self.new_field_keys
        ):
            self._generate_removed_field(package_label, model_name, field_name)

    def _generate_removed_field(self, package_label, model_name, field_name):
        self.add_operation(
            package_label,
            operations.RemoveField(
                model_name=model_name,
                name=field_name,
            ),
            # We might need to depend on the removal of an
            # order_with_respect_to or index/unique_together operation;
            # this is safely ignored if there isn't one
            dependencies=[
                (package_label, model_name, field_name, "order_wrt_unset"),
                (package_label, model_name, field_name, "foo_together_change"),
            ],
        )

    def generate_altered_fields(self):
        """
        Make AlterField operations, or possibly RemovedField/AddField if alter
        isn't possible.
        """
        for package_label, model_name, field_name in sorted(
            self.old_field_keys & self.new_field_keys
        ):
            # Did the field change?
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_field_name = self.renamed_fields.get(
                (package_label, model_name, field_name), field_name
            )
            old_field = self.from_state.models[package_label, old_model_name].get_field(
                old_field_name
            )
            new_field = self.to_state.models[package_label, model_name].get_field(
                field_name
            )
            dependencies = []
            # Implement any model renames on relations; these are handled by RenameModel
            # so we need to exclude them from the comparison
            if hasattr(new_field, "remote_field") and getattr(
                new_field.remote_field, "model", None
            ):
                rename_key = resolve_relation(
                    new_field.remote_field.model, package_label, model_name
                )
                if rename_key in self.renamed_models:
                    new_field.remote_field.model = old_field.remote_field.model
                # Handle ForeignKey which can only have a single to_field.
                remote_field_name = getattr(new_field.remote_field, "field_name", None)
                if remote_field_name:
                    to_field_rename_key = rename_key + (remote_field_name,)
                    if to_field_rename_key in self.renamed_fields:
                        # Repoint both model and field name because to_field
                        # inclusion in ForeignKey.deconstruct() is based on
                        # both.
                        new_field.remote_field.model = old_field.remote_field.model
                        new_field.remote_field.field_name = (
                            old_field.remote_field.field_name
                        )
                # Handle ForeignObjects which can have multiple from_fields/to_fields.
                from_fields = getattr(new_field, "from_fields", None)
                if from_fields:
                    from_rename_key = (package_label, model_name)
                    new_field.from_fields = tuple(
                        [
                            self.renamed_fields.get(
                                from_rename_key + (from_field,), from_field
                            )
                            for from_field in from_fields
                        ]
                    )
                    new_field.to_fields = tuple(
                        [
                            self.renamed_fields.get(rename_key + (to_field,), to_field)
                            for to_field in new_field.to_fields
                        ]
                    )
                dependencies.extend(
                    self._get_dependencies_for_foreign_key(
                        package_label,
                        model_name,
                        new_field,
                        self.to_state,
                    )
                )
            if hasattr(new_field, "remote_field") and getattr(
                new_field.remote_field, "through", None
            ):
                rename_key = resolve_relation(
                    new_field.remote_field.through, package_label, model_name
                )
                if rename_key in self.renamed_models:
                    new_field.remote_field.through = old_field.remote_field.through
            old_field_dec = self.deep_deconstruct(old_field)
            new_field_dec = self.deep_deconstruct(new_field)
            # If the field was confirmed to be renamed it means that only
            # db_column was allowed to change which generate_renamed_fields()
            # already accounts for by adding an AlterField operation.
            if old_field_dec != new_field_dec and old_field_name == field_name:
                both_m2m = old_field.many_to_many and new_field.many_to_many
                neither_m2m = not old_field.many_to_many and not new_field.many_to_many
                if both_m2m or neither_m2m:
                    # Either both fields are m2m or neither is
                    preserve_default = True
                    if (
                        old_field.null
                        and not new_field.null
                        and not new_field.has_default()
                        and not new_field.many_to_many
                    ):
                        field = new_field.clone()
                        new_default = self.questioner.ask_not_null_alteration(
                            field_name, model_name
                        )
                        if new_default is not models.NOT_PROVIDED:
                            field.default = new_default
                            preserve_default = False
                    else:
                        field = new_field
                    self.add_operation(
                        package_label,
                        operations.AlterField(
                            model_name=model_name,
                            name=field_name,
                            field=field,
                            preserve_default=preserve_default,
                        ),
                        dependencies=dependencies,
                    )
                else:
                    # We cannot alter between m2m and concrete fields
                    self._generate_removed_field(package_label, model_name, field_name)
                    self._generate_added_field(package_label, model_name, field_name)

    def create_altered_indexes(self):
        option_name = operations.AddIndex.option_name

        for package_label, model_name in sorted(self.kept_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]

            old_indexes = old_model_state.options[option_name]
            new_indexes = new_model_state.options[option_name]
            added_indexes = [idx for idx in new_indexes if idx not in old_indexes]
            removed_indexes = [idx for idx in old_indexes if idx not in new_indexes]
            renamed_indexes = []
            # Find renamed indexes.
            remove_from_added = []
            remove_from_removed = []
            for new_index in added_indexes:
                new_index_dec = new_index.deconstruct()
                new_index_name = new_index_dec[2].pop("name")
                for old_index in removed_indexes:
                    old_index_dec = old_index.deconstruct()
                    old_index_name = old_index_dec[2].pop("name")
                    # Indexes are the same except for the names.
                    if (
                        new_index_dec == old_index_dec
                        and new_index_name != old_index_name
                    ):
                        renamed_indexes.append((old_index_name, new_index_name, None))
                        remove_from_added.append(new_index)
                        remove_from_removed.append(old_index)

            # Remove renamed indexes from the lists of added and removed
            # indexes.
            added_indexes = [
                idx for idx in added_indexes if idx not in remove_from_added
            ]
            removed_indexes = [
                idx for idx in removed_indexes if idx not in remove_from_removed
            ]

            self.altered_indexes.update(
                {
                    (package_label, model_name): {
                        "added_indexes": added_indexes,
                        "removed_indexes": removed_indexes,
                        "renamed_indexes": renamed_indexes,
                    }
                }
            )

    def generate_added_indexes(self):
        for (package_label, model_name), alt_indexes in self.altered_indexes.items():
            dependencies = self._get_dependencies_for_model(package_label, model_name)
            for index in alt_indexes["added_indexes"]:
                self.add_operation(
                    package_label,
                    operations.AddIndex(
                        model_name=model_name,
                        index=index,
                    ),
                    dependencies=dependencies,
                )

    def generate_removed_indexes(self):
        for (package_label, model_name), alt_indexes in self.altered_indexes.items():
            for index in alt_indexes["removed_indexes"]:
                self.add_operation(
                    package_label,
                    operations.RemoveIndex(
                        model_name=model_name,
                        name=index.name,
                    ),
                )

    def generate_renamed_indexes(self):
        for (package_label, model_name), alt_indexes in self.altered_indexes.items():
            for old_index_name, new_index_name, old_fields in alt_indexes[
                "renamed_indexes"
            ]:
                self.add_operation(
                    package_label,
                    operations.RenameIndex(
                        model_name=model_name,
                        new_name=new_index_name,
                        old_name=old_index_name,
                        old_fields=old_fields,
                    ),
                )

    def create_altered_constraints(self):
        option_name = operations.AddConstraint.option_name
        for package_label, model_name in sorted(self.kept_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]

            old_constraints = old_model_state.options[option_name]
            new_constraints = new_model_state.options[option_name]
            add_constraints = [c for c in new_constraints if c not in old_constraints]
            rem_constraints = [c for c in old_constraints if c not in new_constraints]

            self.altered_constraints.update(
                {
                    (package_label, model_name): {
                        "added_constraints": add_constraints,
                        "removed_constraints": rem_constraints,
                    }
                }
            )

    def generate_added_constraints(self):
        for (
            package_label,
            model_name,
        ), alt_constraints in self.altered_constraints.items():
            dependencies = self._get_dependencies_for_model(package_label, model_name)
            for constraint in alt_constraints["added_constraints"]:
                self.add_operation(
                    package_label,
                    operations.AddConstraint(
                        model_name=model_name,
                        constraint=constraint,
                    ),
                    dependencies=dependencies,
                )

    def generate_removed_constraints(self):
        for (
            package_label,
            model_name,
        ), alt_constraints in self.altered_constraints.items():
            for constraint in alt_constraints["removed_constraints"]:
                self.add_operation(
                    package_label,
                    operations.RemoveConstraint(
                        model_name=model_name,
                        name=constraint.name,
                    ),
                )

    @staticmethod
    def _get_dependencies_for_foreign_key(
        package_label, model_name, field, project_state
    ):
        remote_field_model = None
        if hasattr(field.remote_field, "model"):
            remote_field_model = field.remote_field.model
        else:
            relations = project_state.relations[package_label, model_name]
            for (remote_package_label, remote_model_name), fields in relations.items():
                if any(
                    field == related_field.remote_field
                    for related_field in fields.values()
                ):
                    remote_field_model = f"{remote_package_label}.{remote_model_name}"
                    break
        # Account for FKs to swappable models
        swappable_setting = getattr(field, "swappable_setting", None)
        if swappable_setting is not None:
            dep_package_label = "__setting__"
            dep_object_name = swappable_setting
        else:
            dep_package_label, dep_object_name = resolve_relation(
                remote_field_model,
                package_label,
                model_name,
            )
        dependencies = [(dep_package_label, dep_object_name, None, True)]
        if getattr(field.remote_field, "through", None):
            through_package_label, through_object_name = resolve_relation(
                field.remote_field.through,
                package_label,
                model_name,
            )
            dependencies.append(
                (through_package_label, through_object_name, None, True)
            )
        return dependencies

    def _get_dependencies_for_model(self, package_label, model_name):
        """Return foreign key dependencies of the given model."""
        dependencies = []
        model_state = self.to_state.models[package_label, model_name]
        for field in model_state.fields.values():
            if field.is_relation:
                dependencies.extend(
                    self._get_dependencies_for_foreign_key(
                        package_label,
                        model_name,
                        field,
                        self.to_state,
                    )
                )
        return dependencies

    def _get_altered_foo_together_operations(self, option_name):
        for package_label, model_name in sorted(self.kept_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]

            # We run the old version through the field renames to account for those
            old_value = old_model_state.options.get(option_name)
            old_value = (
                {
                    tuple(
                        self.renamed_fields.get((package_label, model_name, n), n)
                        for n in unique
                    )
                    for unique in old_value
                }
                if old_value
                else set()
            )

            new_value = new_model_state.options.get(option_name)
            new_value = set(new_value) if new_value else set()

            if old_value != new_value:
                dependencies = []
                for foo_togethers in new_value:
                    for field_name in foo_togethers:
                        field = new_model_state.get_field(field_name)
                        if field.remote_field and field.remote_field.model:
                            dependencies.extend(
                                self._get_dependencies_for_foreign_key(
                                    package_label,
                                    model_name,
                                    field,
                                    self.to_state,
                                )
                            )
                yield (
                    old_value,
                    new_value,
                    package_label,
                    model_name,
                    dependencies,
                )

    def _generate_removed_altered_foo_together(self, operation):
        for (
            old_value,
            new_value,
            package_label,
            model_name,
            dependencies,
        ) in self._get_altered_foo_together_operations(operation.option_name):
            removal_value = new_value.intersection(old_value)
            if removal_value or old_value:
                self.add_operation(
                    package_label,
                    operation(
                        name=model_name, **{operation.option_name: removal_value}
                    ),
                    dependencies=dependencies,
                )

    def generate_removed_altered_unique_together(self):
        self._generate_removed_altered_foo_together(operations.AlterUniqueTogether)

    def _generate_altered_foo_together(self, operation):
        for (
            old_value,
            new_value,
            package_label,
            model_name,
            dependencies,
        ) in self._get_altered_foo_together_operations(operation.option_name):
            removal_value = new_value.intersection(old_value)
            if new_value != removal_value:
                self.add_operation(
                    package_label,
                    operation(name=model_name, **{operation.option_name: new_value}),
                    dependencies=dependencies,
                )

    def generate_altered_unique_together(self):
        self._generate_altered_foo_together(operations.AlterUniqueTogether)

    def generate_altered_db_table(self):
        models_to_check = self.kept_model_keys.union(self.kept_unmanaged_keys)
        for package_label, model_name in sorted(models_to_check):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]
            old_db_table_name = old_model_state.options.get("db_table")
            new_db_table_name = new_model_state.options.get("db_table")
            if old_db_table_name != new_db_table_name:
                self.add_operation(
                    package_label,
                    operations.AlterModelTable(
                        name=model_name,
                        table=new_db_table_name,
                    ),
                )

    def generate_altered_db_table_comment(self):
        models_to_check = self.kept_model_keys.union(self.kept_unmanaged_keys)
        for package_label, model_name in sorted(models_to_check):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]

            old_db_table_comment = old_model_state.options.get("db_table_comment")
            new_db_table_comment = new_model_state.options.get("db_table_comment")
            if old_db_table_comment != new_db_table_comment:
                self.add_operation(
                    package_label,
                    operations.AlterModelTableComment(
                        name=model_name,
                        table_comment=new_db_table_comment,
                    ),
                )

    def generate_altered_options(self):
        """
        Work out if any non-schema-affecting options have changed and make an
        operation to represent them in state changes (in case Python code in
        migrations needs them).
        """
        models_to_check = self.kept_model_keys.union(
            self.kept_unmanaged_keys,
            # unmanaged converted to managed
            self.old_unmanaged_keys & self.new_model_keys,
            # managed converted to unmanaged
            self.old_model_keys & self.new_unmanaged_keys,
        )

        for package_label, model_name in sorted(models_to_check):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]
            old_options = {
                key: value
                for key, value in old_model_state.options.items()
                if key in AlterModelOptions.ALTER_OPTION_KEYS
            }
            new_options = {
                key: value
                for key, value in new_model_state.options.items()
                if key in AlterModelOptions.ALTER_OPTION_KEYS
            }
            if old_options != new_options:
                self.add_operation(
                    package_label,
                    operations.AlterModelOptions(
                        name=model_name,
                        options=new_options,
                    ),
                )

    def generate_altered_order_with_respect_to(self):
        for package_label, model_name in sorted(self.kept_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]
            if old_model_state.options.get(
                "order_with_respect_to"
            ) != new_model_state.options.get("order_with_respect_to"):
                # Make sure it comes second if we're adding
                # (removal dependency is part of RemoveField)
                dependencies = []
                if new_model_state.options.get("order_with_respect_to"):
                    dependencies.append(
                        (
                            package_label,
                            model_name,
                            new_model_state.options["order_with_respect_to"],
                            True,
                        )
                    )
                # Actually generate the operation
                self.add_operation(
                    package_label,
                    operations.AlterOrderWithRespectTo(
                        name=model_name,
                        order_with_respect_to=new_model_state.options.get(
                            "order_with_respect_to"
                        ),
                    ),
                    dependencies=dependencies,
                )

    def generate_altered_managers(self):
        for package_label, model_name in sorted(self.kept_model_keys):
            old_model_name = self.renamed_models.get(
                (package_label, model_name), model_name
            )
            old_model_state = self.from_state.models[package_label, old_model_name]
            new_model_state = self.to_state.models[package_label, model_name]
            if old_model_state.managers != new_model_state.managers:
                self.add_operation(
                    package_label,
                    operations.AlterModelManagers(
                        name=model_name,
                        managers=new_model_state.managers,
                    ),
                )

    def arrange_for_graph(self, changes, graph, migration_name=None):
        """
        Take a result from changes() and a MigrationGraph, and fix the names
        and dependencies of the changes so they extend the graph from the leaf
        nodes for each app.
        """
        leaves = graph.leaf_nodes()
        name_map = {}
        for package_label, migrations in list(changes.items()):
            if not migrations:
                continue
            # Find the app label's current leaf node
            app_leaf = None
            for leaf in leaves:
                if leaf[0] == package_label:
                    app_leaf = leaf
                    break
            # Do they want an initial migration for this app?
            if app_leaf is None and not self.questioner.ask_initial(package_label):
                # They don't.
                for migration in migrations:
                    name_map[(package_label, migration.name)] = (
                        package_label,
                        "__first__",
                    )
                del changes[package_label]
                continue
            # Work out the next number in the sequence
            if app_leaf is None:
                next_number = 1
            else:
                next_number = (self.parse_number(app_leaf[1]) or 0) + 1
            # Name each migration
            for i, migration in enumerate(migrations):
                if i == 0 and app_leaf:
                    migration.dependencies.append(app_leaf)
                new_name_parts = ["%04i" % next_number]
                if migration_name:
                    new_name_parts.append(migration_name)
                elif i == 0 and not app_leaf:
                    new_name_parts.append("initial")
                else:
                    new_name_parts.append(migration.suggest_name()[:100])
                new_name = "_".join(new_name_parts)
                name_map[(package_label, migration.name)] = (package_label, new_name)
                next_number += 1
                migration.name = new_name
        # Now fix dependencies
        for migrations in changes.values():
            for migration in migrations:
                migration.dependencies = [
                    name_map.get(d, d) for d in migration.dependencies
                ]
        return changes

    def _trim_to_packages(self, changes, package_labels):
        """
        Take changes from arrange_for_graph() and set of app labels, and return
        a modified set of changes which trims out as many migrations that are
        not in package_labels as possible. Note that some other migrations may
        still be present as they may be required dependencies.
        """
        # Gather other app dependencies in a first pass
        app_dependencies = {}
        for package_label, migrations in changes.items():
            for migration in migrations:
                for dep_package_label, name in migration.dependencies:
                    app_dependencies.setdefault(package_label, set()).add(
                        dep_package_label
                    )
        required_packages = set(package_labels)
        # Keep resolving till there's no change
        old_required_packages = None
        while old_required_packages != required_packages:
            old_required_packages = set(required_packages)
            required_packages.update(
                *[
                    app_dependencies.get(package_label, ())
                    for package_label in required_packages
                ]
            )
        # Remove all migrations that aren't needed
        for package_label in list(changes):
            if package_label not in required_packages:
                del changes[package_label]
        return changes

    @classmethod
    def parse_number(cls, name):
        """
        Given a migration name, try to extract a number from the beginning of
        it. For a squashed migration such as '0001_squashed_0004…', return the
        second number. If no number is found, return None.
        """
        if squashed_match := re.search(r".*_squashed_(\d+)", name):
            return int(squashed_match[1])
        match = re.match(r"^\d+", name)
        if match:
            return int(match[0])
        return None
