import copy
from collections import defaultdict
from contextlib import contextmanager
from functools import cached_property, partial

from plain import models
from plain.exceptions import FieldDoesNotExist
from plain.models.fields import NOT_PROVIDED
from plain.models.fields.related import RECURSIVE_RELATIONSHIP_CONSTANT
from plain.models.migrations.utils import field_is_referenced, get_references
from plain.models.options import DEFAULT_NAMES
from plain.models.registry import ModelsRegistry
from plain.models.registry import models_registry as global_models
from plain.packages import packages_registry
from plain.utils.module_loading import import_string

from .exceptions import InvalidBasesError
from .utils import resolve_relation


def _get_package_label_and_model_name(model, package_label=""):
    if isinstance(model, str):
        split = model.split(".", 1)
        return tuple(split) if len(split) == 2 else (package_label, split[0])
    else:
        return model._meta.package_label, model._meta.model_name


def _get_related_models(m):
    """Return all models that have a direct relationship to the given model."""
    related_models = [
        subclass
        for subclass in m.__subclasses__()
        if issubclass(subclass, models.Model)
    ]
    related_fields_models = set()
    for f in m._meta.get_fields(include_hidden=True):
        if (
            f.is_relation
            and f.related_model is not None
            and not isinstance(f.related_model, str)
        ):
            related_fields_models.add(f.model)
            related_models.append(f.related_model)
    return related_models


def get_related_models_tuples(model):
    """
    Return a list of typical (package_label, model_name) tuples for all related
    models for the given model.
    """
    return {
        (rel_mod._meta.package_label, rel_mod._meta.model_name)
        for rel_mod in _get_related_models(model)
    }


def get_related_models_recursive(model):
    """
    Return all models that have a direct or indirect relationship
    to the given model.

    Relationships are either defined by explicit relational fields, like
    ForeignKey or ManyToManyField, or by inheriting from another
    model (a superclass is related to its subclasses, but not vice versa).
    """
    seen = set()
    queue = _get_related_models(model)
    for rel_mod in queue:
        rel_package_label, rel_model_name = (
            rel_mod._meta.package_label,
            rel_mod._meta.model_name,
        )
        if (rel_package_label, rel_model_name) in seen:
            continue
        seen.add((rel_package_label, rel_model_name))
        queue.extend(_get_related_models(rel_mod))
    return seen - {(model._meta.package_label, model._meta.model_name)}


class ProjectState:
    """
    Represent the entire project's overall state. This is the item that is
    passed around - do it here rather than at the app level so that cross-app
    FKs/etc. resolve properly.
    """

    def __init__(self, models=None, real_packages=None):
        self.models = models or {}
        # Packages to include from main registry, usually unmigrated ones
        if real_packages is None:
            real_packages = set()
        else:
            assert isinstance(real_packages, set)
        self.real_packages = real_packages
        self.is_delayed = False
        # {remote_model_key: {model_key: {field_name: field}}}
        self._relations = None

    @property
    def relations(self):
        if self._relations is None:
            self.resolve_fields_and_relations()
        return self._relations

    def add_model(self, model_state):
        model_key = model_state.package_label, model_state.name_lower
        self.models[model_key] = model_state
        if self._relations is not None:
            self.resolve_model_relations(model_key)
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            self.reload_model(*model_key)

    def remove_model(self, package_label, model_name):
        model_key = package_label, model_name
        del self.models[model_key]
        if self._relations is not None:
            self._relations.pop(model_key, None)
            # Call list() since _relations can change size during iteration.
            for related_model_key, model_relations in list(self._relations.items()):
                model_relations.pop(model_key, None)
                if not model_relations:
                    del self._relations[related_model_key]
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            self.models_registry.unregister_model(*model_key)
            # Need to do this explicitly since unregister_model() doesn't clear
            # the cache automatically (#24513)
            self.models_registry.clear_cache()

    def rename_model(self, package_label, old_name, new_name):
        # Add a new model.
        old_name_lower = old_name.lower()
        new_name_lower = new_name.lower()
        renamed_model = self.models[package_label, old_name_lower].clone()
        renamed_model.name = new_name
        self.models[package_label, new_name_lower] = renamed_model
        # Repoint all fields pointing to the old model to the new one.
        old_model_tuple = (package_label, old_name_lower)
        new_remote_model = f"{package_label}.{new_name}"
        to_reload = set()
        for model_state, name, field, reference in get_references(
            self, old_model_tuple
        ):
            changed_field = None
            if reference.to:
                changed_field = field.clone()
                changed_field.remote_field.model = new_remote_model
            if reference.through:
                if changed_field is None:
                    changed_field = field.clone()
                changed_field.remote_field.through = new_remote_model
            if changed_field:
                model_state.fields[name] = changed_field
                to_reload.add((model_state.package_label, model_state.name_lower))
        if self._relations is not None:
            old_name_key = package_label, old_name_lower
            new_name_key = package_label, new_name_lower
            if old_name_key in self._relations:
                self._relations[new_name_key] = self._relations.pop(old_name_key)
            for model_relations in self._relations.values():
                if old_name_key in model_relations:
                    model_relations[new_name_key] = model_relations.pop(old_name_key)
        # Reload models related to old model before removing the old model.
        self.reload_models(to_reload, delay=True)
        # Remove the old model.
        self.remove_model(package_label, old_name_lower)
        self.reload_model(package_label, new_name_lower, delay=True)

    def alter_model_options(self, package_label, model_name, options, option_keys=None):
        model_state = self.models[package_label, model_name]
        model_state.options = {**model_state.options, **options}
        if option_keys:
            for key in option_keys:
                if key not in options:
                    model_state.options.pop(key, False)
        self.reload_model(package_label, model_name, delay=True)

    def alter_model_managers(self, package_label, model_name, managers):
        model_state = self.models[package_label, model_name]
        model_state.managers = list(managers)
        self.reload_model(package_label, model_name, delay=True)

    def _append_option(self, package_label, model_name, option_name, obj):
        model_state = self.models[package_label, model_name]
        model_state.options[option_name] = [*model_state.options[option_name], obj]
        self.reload_model(package_label, model_name, delay=True)

    def _remove_option(self, package_label, model_name, option_name, obj_name):
        model_state = self.models[package_label, model_name]
        objs = model_state.options[option_name]
        model_state.options[option_name] = [obj for obj in objs if obj.name != obj_name]
        self.reload_model(package_label, model_name, delay=True)

    def add_index(self, package_label, model_name, index):
        self._append_option(package_label, model_name, "indexes", index)

    def remove_index(self, package_label, model_name, index_name):
        self._remove_option(package_label, model_name, "indexes", index_name)

    def rename_index(self, package_label, model_name, old_index_name, new_index_name):
        model_state = self.models[package_label, model_name]
        objs = model_state.options["indexes"]

        new_indexes = []
        for obj in objs:
            if obj.name == old_index_name:
                obj = obj.clone()
                obj.name = new_index_name
            new_indexes.append(obj)

        model_state.options["indexes"] = new_indexes
        self.reload_model(package_label, model_name, delay=True)

    def add_constraint(self, package_label, model_name, constraint):
        self._append_option(package_label, model_name, "constraints", constraint)

    def remove_constraint(self, package_label, model_name, constraint_name):
        self._remove_option(package_label, model_name, "constraints", constraint_name)

    def add_field(self, package_label, model_name, name, field, preserve_default):
        # If preserve default is off, don't use the default for future state.
        if not preserve_default:
            field = field.clone()
            field.default = NOT_PROVIDED
        else:
            field = field
        model_key = package_label, model_name
        self.models[model_key].fields[name] = field
        if self._relations is not None:
            self.resolve_model_field_relations(model_key, name, field)
        # Delay rendering of relationships if it's not a relational field.
        delay = not field.is_relation
        self.reload_model(*model_key, delay=delay)

    def remove_field(self, package_label, model_name, name):
        model_key = package_label, model_name
        model_state = self.models[model_key]
        old_field = model_state.fields.pop(name)
        if self._relations is not None:
            self.resolve_model_field_relations(model_key, name, old_field)
        # Delay rendering of relationships if it's not a relational field.
        delay = not old_field.is_relation
        self.reload_model(*model_key, delay=delay)

    def alter_field(self, package_label, model_name, name, field, preserve_default):
        if not preserve_default:
            field = field.clone()
            field.default = NOT_PROVIDED
        else:
            field = field
        model_key = package_label, model_name
        fields = self.models[model_key].fields
        if self._relations is not None:
            old_field = fields.pop(name)
            if old_field.is_relation:
                self.resolve_model_field_relations(model_key, name, old_field)
            fields[name] = field
            if field.is_relation:
                self.resolve_model_field_relations(model_key, name, field)
        else:
            fields[name] = field
        # TODO: investigate if old relational fields must be reloaded or if
        # it's sufficient if the new field is (#27737).
        # Delay rendering of relationships if it's not a relational field and
        # not referenced by a foreign key.
        delay = not field.is_relation and not field_is_referenced(
            self, model_key, (name, field)
        )
        self.reload_model(*model_key, delay=delay)

    def rename_field(self, package_label, model_name, old_name, new_name):
        model_key = package_label, model_name
        model_state = self.models[model_key]
        # Rename the field.
        fields = model_state.fields
        try:
            found = fields.pop(old_name)
        except KeyError:
            raise FieldDoesNotExist(
                f"{package_label}.{model_name} has no field named '{old_name}'"
            )
        fields[new_name] = found
        for field in fields.values():
            # Fix from_fields to refer to the new field.
            from_fields = getattr(field, "from_fields", None)
            if from_fields:
                field.from_fields = tuple(
                    [
                        new_name if from_field_name == old_name else from_field_name
                        for from_field_name in from_fields
                    ]
                )

        # Fix to_fields to refer to the new field.
        delay = True
        references = get_references(self, model_key, (old_name, found))
        for *_, field, reference in references:
            delay = False
            if reference.to:
                remote_field, to_fields = reference.to
                if getattr(remote_field, "field_name", None) == old_name:
                    remote_field.field_name = new_name
                if to_fields:
                    field.to_fields = tuple(
                        [
                            new_name if to_field_name == old_name else to_field_name
                            for to_field_name in to_fields
                        ]
                    )
        if self._relations is not None:
            old_name_lower = old_name.lower()
            new_name_lower = new_name.lower()
            for to_model in self._relations.values():
                if old_name_lower in to_model[model_key]:
                    field = to_model[model_key].pop(old_name_lower)
                    field.name = new_name_lower
                    to_model[model_key][new_name_lower] = field
        self.reload_model(*model_key, delay=delay)

    def _find_reload_model(self, package_label, model_name, delay=False):
        if delay:
            self.is_delayed = True

        related_models = set()

        try:
            old_model = self.models_registry.get_model(package_label, model_name)
        except LookupError:
            pass
        else:
            # Get all relations to and from the old model before reloading,
            # as _meta.models_registry may change
            if delay:
                related_models = get_related_models_tuples(old_model)
            else:
                related_models = get_related_models_recursive(old_model)

        # Get all outgoing references from the model to be rendered
        model_state = self.models[(package_label, model_name)]
        # Directly related models are the models pointed to by ForeignKeys and ManyToManyFields.
        direct_related_models = set()
        for field in model_state.fields.values():
            if field.is_relation:
                if field.remote_field.model == RECURSIVE_RELATIONSHIP_CONSTANT:
                    continue
                rel_package_label, rel_model_name = _get_package_label_and_model_name(
                    field.related_model, package_label
                )
                direct_related_models.add((rel_package_label, rel_model_name.lower()))

        # For all direct related models recursively get all related models.
        related_models.update(direct_related_models)
        for rel_package_label, rel_model_name in direct_related_models:
            try:
                rel_model = self.models_registry.get_model(
                    rel_package_label, rel_model_name
                )
            except LookupError:
                pass
            else:
                if delay:
                    related_models.update(get_related_models_tuples(rel_model))
                else:
                    related_models.update(get_related_models_recursive(rel_model))

        # Include the model itself
        related_models.add((package_label, model_name))

        return related_models

    def reload_model(self, package_label, model_name, delay=False):
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            related_models = self._find_reload_model(package_label, model_name, delay)
            self._reload(related_models)

    def reload_models(self, models, delay=True):
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            related_models = set()
            for package_label, model_name in models:
                related_models.update(
                    self._find_reload_model(package_label, model_name, delay)
                )
            self._reload(related_models)

    def _reload(self, related_models):
        # Unregister all related models
        with self.models_registry.bulk_update():
            for rel_package_label, rel_model_name in related_models:
                self.models_registry.unregister_model(rel_package_label, rel_model_name)

        states_to_be_rendered = []
        # Gather all models states of those models that will be rerendered.
        # This includes:
        # 1. All related models of unmigrated packages
        for model_state in self.models_registry.real_models:
            if (model_state.package_label, model_state.name_lower) in related_models:
                states_to_be_rendered.append(model_state)

        # 2. All related models of migrated packages
        for rel_package_label, rel_model_name in related_models:
            try:
                model_state = self.models[rel_package_label, rel_model_name]
            except KeyError:
                pass
            else:
                states_to_be_rendered.append(model_state)

        # Render all models
        self.models_registry.render_multiple(states_to_be_rendered)

    def update_model_field_relation(
        self,
        model,
        model_key,
        field_name,
        field,
        concretes,
    ):
        remote_model_key = resolve_relation(model, *model_key)
        if (
            remote_model_key[0] not in self.real_packages
            and remote_model_key in concretes
        ):
            remote_model_key = concretes[remote_model_key]
        relations_to_remote_model = self._relations[remote_model_key]
        if field_name in self.models[model_key].fields:
            # The assert holds because it's a new relation, or an altered
            # relation, in which case references have been removed by
            # alter_field().
            assert field_name not in relations_to_remote_model[model_key]
            relations_to_remote_model[model_key][field_name] = field
        else:
            del relations_to_remote_model[model_key][field_name]
            if not relations_to_remote_model[model_key]:
                del relations_to_remote_model[model_key]

    def resolve_model_field_relations(
        self,
        model_key,
        field_name,
        field,
        concretes=None,
    ):
        remote_field = field.remote_field
        if not remote_field:
            return
        if concretes is None:
            concretes = self._get_concrete_models_mapping()

        self.update_model_field_relation(
            remote_field.model,
            model_key,
            field_name,
            field,
            concretes,
        )

        through = getattr(remote_field, "through", None)
        if not through:
            return
        self.update_model_field_relation(
            through, model_key, field_name, field, concretes
        )

    def resolve_model_relations(self, model_key, concretes=None):
        if concretes is None:
            concretes = self._get_concrete_models_mapping()

        model_state = self.models[model_key]
        for field_name, field in model_state.fields.items():
            self.resolve_model_field_relations(model_key, field_name, field, concretes)

    def resolve_fields_and_relations(self):
        # Resolve fields.
        for model_state in self.models.values():
            for field_name, field in model_state.fields.items():
                field.name = field_name
        # Resolve relations.
        # {remote_model_key: {model_key: {field_name: field}}}
        self._relations = defaultdict(partial(defaultdict, dict))
        concretes = self._get_concrete_models_mapping()

        for model_key in concretes:
            self.resolve_model_relations(model_key, concretes)

    def _get_concrete_models_mapping(self):
        concrete_models_mapping = {}
        for model_key, model_state in self.models.items():
            concrete_models_mapping[model_key] = model_key
        return concrete_models_mapping

    def clone(self):
        """Return an exact copy of this ProjectState."""
        new_state = ProjectState(
            models={k: v.clone() for k, v in self.models.items()},
            real_packages=self.real_packages,
        )
        if "models_registry" in self.__dict__:
            new_state.models_registry = self.models_registry.clone()
        new_state.is_delayed = self.is_delayed
        return new_state

    def clear_delayed_models_cache(self):
        if self.is_delayed and "models_registry" in self.__dict__:
            del self.__dict__["models_registry"]

    @cached_property
    def models_registry(self):
        return StateModelsRegistry(self.real_packages, self.models)

    @classmethod
    def from_models_registry(cls, models_registry):
        """Take an Packages and return a ProjectState matching it."""
        app_models = {}
        for model in models_registry.get_models():
            model_state = ModelState.from_model(model)
            app_models[(model_state.package_label, model_state.name_lower)] = (
                model_state
            )
        return cls(app_models)

    def __eq__(self, other):
        return self.models == other.models and self.real_packages == other.real_packages


class StateModelsRegistry(ModelsRegistry):
    """
    Subclass of the global Packages registry class to better handle dynamic model
    additions and removals.
    """

    def __init__(self, real_packages, models):
        # Any packages in self.real_packages should have all their models included
        # in the render. We don't use the original model instances as there
        # are some variables that refer to the Packages object.
        # FKs/M2Ms from real packages are also not included as they just
        # mess things up with partial states (due to lack of dependencies)
        self.real_models = []
        for package_label in real_packages:
            for model in global_models.get_models(package_label=package_label):
                self.real_models.append(ModelState.from_model(model, exclude_rels=True))

        super().__init__()

        self.render_multiple([*models.values(), *self.real_models])

        self.ready = True

        # There shouldn't be any operations pending at this point.
        from plain.models.preflight import _check_lazy_references

        if errors := _check_lazy_references(self, packages_registry):
            raise ValueError("\n".join(error.msg for error in errors))

    @contextmanager
    def bulk_update(self):
        # Avoid clearing each model's cache for each change. Instead, clear
        # all caches when we're finished updating the model instances.
        ready = self.ready
        self.ready = False
        try:
            yield
        finally:
            self.ready = ready
            self.clear_cache()

    def render_multiple(self, model_states):
        # We keep trying to render the models in a loop, ignoring invalid
        # base errors, until the size of the unrendered models doesn't
        # decrease by at least one, meaning there's a base dependency loop/
        # missing base.
        if not model_states:
            return
        # Prevent that all model caches are expired for each render.
        with self.bulk_update():
            unrendered_models = model_states
            while unrendered_models:
                new_unrendered_models = []
                for model in unrendered_models:
                    try:
                        model.render(self)
                    except InvalidBasesError:
                        new_unrendered_models.append(model)
                if len(new_unrendered_models) == len(unrendered_models):
                    raise InvalidBasesError(
                        f"Cannot resolve bases for {new_unrendered_models!r}\nThis can happen if you are "
                        "inheriting models from an app with migrations (e.g. "
                        "contrib.auth)\n in an app with no migrations"
                    )
                unrendered_models = new_unrendered_models

    def clone(self):
        """Return a clone of this registry."""
        clone = StateModelsRegistry([], {})
        clone.all_models = copy.deepcopy(self.all_models)

        # No need to actually clone them, they'll never change
        clone.real_models = self.real_models
        return clone

    def register_model(self, package_label, model):
        self.all_models[package_label][model._meta.model_name] = model
        self.do_pending_operations(model)
        self.clear_cache()

    def unregister_model(self, package_label, model_name):
        try:
            del self.all_models[package_label][model_name]
        except KeyError:
            pass


class ModelState:
    """
    Represent a Plain Model. Don't use the actual Model class as it's not
    designed to have its options changed - instead, mutate this one and then
    render it into a Model as required.

    Note that while you are allowed to mutate .fields, you are not allowed
    to mutate the Field instances inside there themselves - you must instead
    assign new ones, as these are not detached during a clone.
    """

    def __init__(
        self, package_label, name, fields, options=None, bases=None, managers=None
    ):
        self.package_label = package_label
        self.name = name
        self.fields = dict(fields)
        self.options = options or {}
        self.options.setdefault("indexes", [])
        self.options.setdefault("constraints", [])
        self.bases = bases or (models.Model,)
        self.managers = managers or []
        for name, field in self.fields.items():
            # Sanity-check that fields are NOT already bound to a model.
            if hasattr(field, "model"):
                raise ValueError(
                    f'ModelState.fields cannot be bound to a model - "{name}" is.'
                )
            # Sanity-check that relation fields are NOT referring to a model class.
            if field.is_relation and hasattr(field.related_model, "_meta"):
                raise ValueError(
                    f'ModelState.fields cannot refer to a model class - "{name}.to" does. '
                    "Use a string reference instead."
                )
            if field.many_to_many and hasattr(field.remote_field.through, "_meta"):
                raise ValueError(
                    f'ModelState.fields cannot refer to a model class - "{name}.through" '
                    "does. Use a string reference instead."
                )
        # Sanity-check that indexes have their name set.
        for index in self.options["indexes"]:
            if not index.name:
                raise ValueError(
                    "Indexes passed to ModelState require a name attribute. "
                    f"{index!r} doesn't have one."
                )

    @cached_property
    def name_lower(self):
        return self.name.lower()

    def get_field(self, field_name):
        return self.fields[field_name]

    @classmethod
    def from_model(cls, model, exclude_rels=False):
        """Given a model, return a ModelState representing it."""
        # Deconstruct the fields
        fields = []
        for field in model._meta.local_fields:
            if getattr(field, "remote_field", None) and exclude_rels:
                continue
            name = field.name
            try:
                fields.append((name, field.clone()))
            except TypeError as e:
                raise TypeError(
                    f"Couldn't reconstruct field {name} on {model._meta.label}: {e}"
                )
        if not exclude_rels:
            for field in model._meta.local_many_to_many:
                name = field.name
                try:
                    fields.append((name, field.clone()))
                except TypeError as e:
                    raise TypeError(
                        f"Couldn't reconstruct m2m field {name} on {model._meta.object_name}: {e}"
                    )
        # Extract the options
        options = {}
        for name in DEFAULT_NAMES:
            # Ignore some special options
            if name in ["models_registry", "package_label"]:
                continue
            elif name in model._meta.original_attrs:
                if name == "indexes":
                    indexes = [idx.clone() for idx in model._meta.indexes]
                    for index in indexes:
                        if not index.name:
                            index.set_name_with_model(model)
                    options["indexes"] = indexes
                elif name == "constraints":
                    options["constraints"] = [
                        con.clone() for con in model._meta.constraints
                    ]
                else:
                    options[name] = model._meta.original_attrs[name]

        def flatten_bases(model):
            bases = []
            for base in model.__bases__:
                bases.append(base)
            return bases

        # We can't rely on __mro__ directly because we only want to flatten
        # abstract models and not the whole tree. However by recursing on
        # __bases__ we may end up with duplicates and ordering issues, we
        # therefore discard any duplicates and reorder the bases according
        # to their index in the MRO.
        flattened_bases = sorted(
            set(flatten_bases(model)), key=lambda x: model.__mro__.index(x)
        )

        # Make our record
        bases = tuple(
            (base._meta.label_lower if hasattr(base, "_meta") else base)
            for base in flattened_bases
        )
        # Ensure at least one base inherits from models.Model
        if not any(
            (isinstance(base, str) or issubclass(base, models.Model)) for base in bases
        ):
            bases = (models.Model,)

        managers = []
        manager_names = set()
        default_manager_shim = None
        for manager in model._meta.managers:
            if manager.name in manager_names:
                # Skip overridden managers.
                continue
            elif manager.use_in_migrations:
                # Copy managers usable in migrations.
                new_manager = copy.copy(manager)
                new_manager._set_creation_counter()
            elif manager is model._base_manager or manager is model._default_manager:
                # Shim custom managers used as default and base managers.
                new_manager = models.Manager()
                new_manager.model = manager.model
                new_manager.name = manager.name
                if manager is model._default_manager:
                    default_manager_shim = new_manager
            else:
                continue
            manager_names.add(manager.name)
            managers.append((manager.name, new_manager))

        # Ignore a shimmed default manager called objects if it's the only one.
        if managers == [("objects", default_manager_shim)]:
            managers = []

        # Construct the new ModelState
        return cls(
            model._meta.package_label,
            model._meta.object_name,
            fields,
            options,
            bases,
            managers,
        )

    def construct_managers(self):
        """Deep-clone the managers using deconstruction."""
        # Sort all managers by their creation counter
        sorted_managers = sorted(self.managers, key=lambda v: v[1].creation_counter)
        for mgr_name, manager in sorted_managers:
            as_manager, manager_path, qs_path, args, kwargs = manager.deconstruct()
            if as_manager:
                qs_class = import_string(qs_path)
                yield mgr_name, qs_class.as_manager()
            else:
                manager_class = import_string(manager_path)
                yield mgr_name, manager_class(*args, **kwargs)

    def clone(self):
        """Return an exact copy of this ModelState."""
        return self.__class__(
            package_label=self.package_label,
            name=self.name,
            fields=dict(self.fields),
            # Since options are shallow-copied here, operations such as
            # AddIndex must replace their option (e.g 'indexes') rather
            # than mutating it.
            options=dict(self.options),
            bases=self.bases,
            managers=list(self.managers),
        )

    def render(self, models_registry):
        """Create a Model object from our current state into the given packages."""
        # First, make a Meta object
        meta_contents = {
            "package_label": self.package_label,
            "models_registry": models_registry,
            **self.options,
        }
        meta = type("Meta", (), meta_contents)
        # Then, work out our bases
        try:
            bases = tuple(
                (models_registry.get_model(base) if isinstance(base, str) else base)
                for base in self.bases
            )
        except LookupError:
            raise InvalidBasesError(
                f"Cannot resolve one or more bases from {self.bases!r}"
            )
        # Clone fields for the body, add other bits.
        body = {name: field.clone() for name, field in self.fields.items()}
        body["Meta"] = meta
        body["__module__"] = "__fake__"

        # Restore managers
        body.update(self.construct_managers())
        # Then, make a Model object (models_registry.register_model is called in __new__)
        model_class = type(self.name, bases, body)
        from plain.models import register_model

        # Register it to the models_registry associated with the model meta
        # (could probably do this directly right here too...)
        register_model(model_class)

        return model_class

    def get_index_by_name(self, name):
        for index in self.options["indexes"]:
            if index.name == name:
                return index
        raise ValueError(f"No index named {name} on model {self.name}")

    def get_constraint_by_name(self, name):
        for constraint in self.options["constraints"]:
            if constraint.name == name:
                return constraint
        raise ValueError(f"No constraint named {name} on model {self.name}")

    def __repr__(self):
        return f"<{self.__class__.__name__}: '{self.package_label}.{self.name}'>"

    def __eq__(self, other):
        return (
            (self.package_label == other.package_label)
            and (self.name == other.name)
            and (len(self.fields) == len(other.fields))
            and all(
                k1 == k2 and f1.deconstruct()[1:] == f2.deconstruct()[1:]
                for (k1, f1), (k2, f2) in zip(
                    sorted(self.fields.items()),
                    sorted(other.fields.items()),
                )
            )
            and (self.options == other.options)
            and (self.bases == other.bases)
            and (self.managers == other.managers)
        )
