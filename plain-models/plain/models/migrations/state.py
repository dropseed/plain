from __future__ import annotations

import copy
from collections import defaultdict
from contextlib import contextmanager
from functools import cached_property, partial
from typing import TYPE_CHECKING, Any

from plain import models
from plain.models.exceptions import FieldDoesNotExist
from plain.models.fields import NOT_PROVIDED
from plain.models.fields.related import RECURSIVE_RELATIONSHIP_CONSTANT
from plain.models.meta import Meta
from plain.models.migrations.utils import field_is_referenced, get_references
from plain.models.registry import ModelsRegistry
from plain.models.registry import models_registry as global_models
from plain.packages import packages_registry

from .exceptions import InvalidBasesError
from .utils import resolve_relation

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable

    from plain.models.fields import Field


def _get_package_label_and_model_name(
    model: str | type[models.Model], package_label: str = ""
) -> tuple[str, str]:
    if isinstance(model, str):
        split = model.split(".", 1)
        return tuple(split) if len(split) == 2 else (package_label, split[0])  # type: ignore[return-value]
    else:
        return model.model_options.package_label, model.model_options.model_name


def _get_related_models(m: type[models.Model]) -> list[type[models.Model]]:
    """Return all models that have a direct relationship to the given model."""
    related_models = [
        subclass
        for subclass in m.__subclasses__()
        if issubclass(subclass, models.Model)
    ]
    related_fields_models = set()
    for f in m._model_meta.get_fields(include_hidden=True):
        if (
            f.is_relation  # type: ignore[attr-defined]
            and f.related_model is not None  # type: ignore[attr-defined]
            and not isinstance(f.related_model, str)  # type: ignore[attr-defined]
        ):
            related_fields_models.add(f.model)  # type: ignore[attr-defined]
            related_models.append(f.related_model)  # type: ignore[attr-defined]
    return related_models


def get_related_models_tuples(model: type[models.Model]) -> set[tuple[str, str]]:
    """
    Return a list of typical (package_label, model_name) tuples for all related
    models for the given model.
    """
    return {
        (rel_mod.model_options.package_label, rel_mod.model_options.model_name)
        for rel_mod in _get_related_models(model)
    }


def get_related_models_recursive(model: type[models.Model]) -> set[tuple[str, str]]:
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
            rel_mod.model_options.package_label,
            rel_mod.model_options.model_name,
        )
        if (rel_package_label, rel_model_name) in seen:
            continue
        seen.add((rel_package_label, rel_model_name))
        queue.extend(_get_related_models(rel_mod))
    return seen - {(model.model_options.package_label, model.model_options.model_name)}


class ProjectState:
    """
    Represent the entire project's overall state. This is the item that is
    passed around - do it here rather than at the app level so that cross-app
    FKs/etc. resolve properly.
    """

    def __init__(
        self,
        models: dict[tuple[str, str], ModelState] | None = None,
        real_packages: set[str] | None = None,
    ):
        self.models = models or {}
        # Packages to include from main registry, usually unmigrated ones
        if real_packages is None:
            real_packages = set()
        else:
            assert isinstance(real_packages, set)
        self.real_packages = real_packages
        self.is_delayed = False
        # {remote_model_key: {model_key: {field_name: field}}}
        self._relations: (
            dict[tuple[str, str], dict[tuple[str, str], dict[str, Field]]] | None
        ) = None

    @property
    def relations(
        self,
    ) -> dict[tuple[str, str], dict[tuple[str, str], dict[str, Field]]]:
        if self._relations is None:
            self.resolve_fields_and_relations()
        return self._relations  # type: ignore[return-value]

    def add_model(self, model_state: ModelState) -> None:
        model_key = model_state.package_label, model_state.name_lower
        self.models[model_key] = model_state
        if self._relations is not None:
            self.resolve_model_relations(model_key)
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            self.reload_model(*model_key)

    def remove_model(self, package_label: str, model_name: str) -> None:
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

    def rename_model(self, package_label: str, old_name: str, new_name: str) -> None:
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
                changed_field.remote_field.model = new_remote_model  # type: ignore[attr-defined]
            if reference.through:
                if changed_field is None:
                    changed_field = field.clone()
                changed_field.remote_field.through = new_remote_model  # type: ignore[attr-defined]
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

    def alter_model_options(
        self,
        package_label: str,
        model_name: str,
        options: dict[str, Any],
        option_keys: Iterable[str] | None = None,
    ) -> None:
        model_state = self.models[package_label, model_name]
        model_state.options = {**model_state.options, **options}
        if option_keys:
            for key in option_keys:
                if key not in options:
                    model_state.options.pop(key, False)
        self.reload_model(package_label, model_name, delay=True)

    def _append_option(
        self, package_label: str, model_name: str, option_name: str, obj: Any
    ) -> None:
        model_state = self.models[package_label, model_name]
        model_state.options[option_name] = [*model_state.options[option_name], obj]
        self.reload_model(package_label, model_name, delay=True)

    def _remove_option(
        self, package_label: str, model_name: str, option_name: str, obj_name: str
    ) -> None:
        model_state = self.models[package_label, model_name]
        objs = model_state.options[option_name]
        model_state.options[option_name] = [
            obj
            for obj in objs
            if obj.name != obj_name  # type: ignore[attr-defined]
        ]
        self.reload_model(package_label, model_name, delay=True)

    def add_index(self, package_label: str, model_name: str, index: Any) -> None:
        self._append_option(package_label, model_name, "indexes", index)

    def remove_index(
        self, package_label: str, model_name: str, index_name: str
    ) -> None:
        self._remove_option(package_label, model_name, "indexes", index_name)

    def rename_index(
        self,
        package_label: str,
        model_name: str,
        old_index_name: str,
        new_index_name: str,
    ) -> None:
        model_state = self.models[package_label, model_name]
        objs = model_state.options["indexes"]

        new_indexes = []
        for obj in objs:
            if obj.name == old_index_name:  # type: ignore[attr-defined]
                obj = obj.clone()  # type: ignore[attr-defined]
                obj.name = new_index_name  # type: ignore[attr-defined]
            new_indexes.append(obj)

        model_state.options["indexes"] = new_indexes
        self.reload_model(package_label, model_name, delay=True)

    def add_constraint(
        self, package_label: str, model_name: str, constraint: Any
    ) -> None:
        self._append_option(package_label, model_name, "constraints", constraint)

    def remove_constraint(
        self, package_label: str, model_name: str, constraint_name: str
    ) -> None:
        self._remove_option(package_label, model_name, "constraints", constraint_name)

    def add_field(
        self,
        package_label: str,
        model_name: str,
        name: str,
        field: Field,
        preserve_default: bool,
    ) -> None:
        # If preserve default is off, don't use the default for future state.
        if not preserve_default:
            field = field.clone()
            field.default = NOT_PROVIDED  # type: ignore[attr-defined]
        else:
            field = field
        model_key = package_label, model_name
        self.models[model_key].fields[name] = field
        if self._relations is not None:
            self.resolve_model_field_relations(model_key, name, field)
        # Delay rendering of relationships if it's not a relational field.
        delay = not field.is_relation  # type: ignore[attr-defined]
        self.reload_model(*model_key, delay=delay)

    def remove_field(self, package_label: str, model_name: str, name: str) -> None:
        model_key = package_label, model_name
        model_state = self.models[model_key]
        old_field = model_state.fields.pop(name)
        if self._relations is not None:
            self.resolve_model_field_relations(model_key, name, old_field)
        # Delay rendering of relationships if it's not a relational field.
        delay = not old_field.is_relation  # type: ignore[attr-defined]
        self.reload_model(*model_key, delay=delay)

    def alter_field(
        self,
        package_label: str,
        model_name: str,
        name: str,
        field: Field,
        preserve_default: bool,
    ) -> None:
        if not preserve_default:
            field = field.clone()
            field.default = NOT_PROVIDED  # type: ignore[attr-defined]
        else:
            field = field
        model_key = package_label, model_name
        fields = self.models[model_key].fields
        if self._relations is not None:
            old_field = fields.pop(name)
            if old_field.is_relation:  # type: ignore[attr-defined]
                self.resolve_model_field_relations(model_key, name, old_field)
            fields[name] = field
            if field.is_relation:  # type: ignore[attr-defined]
                self.resolve_model_field_relations(model_key, name, field)
        else:
            fields[name] = field
        # TODO: investigate if old relational fields must be reloaded or if
        # it's sufficient if the new field is (#27737).
        # Delay rendering of relationships if it's not a relational field and
        # not referenced by a foreign key.
        delay = not field.is_relation and not field_is_referenced(  # type: ignore[attr-defined]
            self, model_key, (name, field)
        )
        self.reload_model(*model_key, delay=delay)

    def rename_field(
        self, package_label: str, model_name: str, old_name: str, new_name: str
    ) -> None:
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
        # Check if there are any references to this field
        references = get_references(self, model_key, (old_name, found))
        delay = not bool(references)
        if self._relations is not None:
            old_name_lower = old_name.lower()
            new_name_lower = new_name.lower()
            for to_model in self._relations.values():
                if old_name_lower in to_model[model_key]:
                    field = to_model[model_key].pop(old_name_lower)
                    field.name = new_name_lower  # type: ignore[attr-defined]
                    to_model[model_key][new_name_lower] = field
        self.reload_model(*model_key, delay=delay)

    def _find_reload_model(
        self, package_label: str, model_name: str, delay: bool = False
    ) -> set[tuple[str, str]]:
        if delay:
            self.is_delayed = True

        related_models: set[tuple[str, str]] = set()

        try:
            old_model = self.models_registry.get_model(package_label, model_name)
        except LookupError:
            pass
        else:
            # Get all relations to and from the old model before reloading,
            # as _model_meta.models_registry may change
            if delay:
                related_models = get_related_models_tuples(old_model)
            else:
                related_models = get_related_models_recursive(old_model)

        # Get all outgoing references from the model to be rendered
        model_state = self.models[(package_label, model_name)]
        # Directly related models are the models pointed to by ForeignKeys and ManyToManyFields.
        direct_related_models = set()
        for field in model_state.fields.values():
            if field.is_relation:  # type: ignore[attr-defined]
                if field.remote_field.model == RECURSIVE_RELATIONSHIP_CONSTANT:  # type: ignore[attr-defined]
                    continue
                rel_package_label, rel_model_name = _get_package_label_and_model_name(
                    field.related_model,
                    package_label,  # type: ignore[attr-defined]
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

    def reload_model(
        self, package_label: str, model_name: str, delay: bool = False
    ) -> None:
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            related_models = self._find_reload_model(package_label, model_name, delay)
            self._reload(related_models)

    def reload_models(self, models: set[tuple[str, str]], delay: bool = True) -> None:
        if "models_registry" in self.__dict__:  # hasattr would cache the property
            related_models = set()
            for package_label, model_name in models:
                related_models.update(
                    self._find_reload_model(package_label, model_name, delay)
                )
            self._reload(related_models)

    def _reload(self, related_models: set[tuple[str, str]]) -> None:
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
        model: str | type[models.Model],
        model_key: tuple[str, str],
        field_name: str,
        field: Field,
        concretes: dict[tuple[str, str], tuple[str, str]],
    ) -> None:
        remote_model_key = resolve_relation(model, *model_key)
        if (
            remote_model_key[0] not in self.real_packages
            and remote_model_key in concretes
        ):
            remote_model_key = concretes[remote_model_key]
        relations_to_remote_model = self._relations[remote_model_key]  # type: ignore[index]
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
        model_key: tuple[str, str],
        field_name: str,
        field: Field,
        concretes: dict[tuple[str, str], tuple[str, str]] | None = None,
    ) -> None:
        remote_field = field.remote_field  # type: ignore[attr-defined]
        if not remote_field:
            return None
        if concretes is None:
            concretes = self._get_concrete_models_mapping()

        self.update_model_field_relation(
            remote_field.model,  # type: ignore[attr-defined]
            model_key,
            field_name,
            field,
            concretes,
        )

        through = getattr(remote_field, "through", None)
        if not through:
            return None
        self.update_model_field_relation(
            through, model_key, field_name, field, concretes
        )

    def resolve_model_relations(
        self,
        model_key: tuple[str, str],
        concretes: dict[tuple[str, str], tuple[str, str]] | None = None,
    ) -> None:
        if concretes is None:
            concretes = self._get_concrete_models_mapping()

        model_state = self.models[model_key]
        for field_name, field in model_state.fields.items():
            self.resolve_model_field_relations(model_key, field_name, field, concretes)

    def resolve_fields_and_relations(self) -> None:
        # Resolve fields.
        for model_state in self.models.values():
            for field_name, field in model_state.fields.items():
                field.name = field_name  # type: ignore[attr-defined]
        # Resolve relations.
        # {remote_model_key: {model_key: {field_name: field}}}
        self._relations = defaultdict(partial(defaultdict, dict))
        concretes = self._get_concrete_models_mapping()

        for model_key in concretes:
            self.resolve_model_relations(model_key, concretes)

    def _get_concrete_models_mapping(self) -> dict[tuple[str, str], tuple[str, str]]:
        concrete_models_mapping = {}
        for model_key, model_state in self.models.items():
            concrete_models_mapping[model_key] = model_key
        return concrete_models_mapping

    def clone(self) -> ProjectState:
        """Return an exact copy of this ProjectState."""
        new_state = ProjectState(
            models={k: v.clone() for k, v in self.models.items()},
            real_packages=self.real_packages,
        )
        if "models_registry" in self.__dict__:
            new_state.models_registry = self.models_registry.clone()
        new_state.is_delayed = self.is_delayed
        return new_state

    def clear_delayed_models_cache(self) -> None:
        if self.is_delayed and "models_registry" in self.__dict__:
            del self.__dict__["models_registry"]

    @cached_property
    def models_registry(self) -> StateModelsRegistry:
        return StateModelsRegistry(self.real_packages, self.models)

    @classmethod
    def from_models_registry(cls, models_registry: ModelsRegistry) -> ProjectState:
        """Take an Packages and return a ProjectState matching it."""
        app_models = {}
        for model in models_registry.get_models():
            model_state = ModelState.from_model(model)
            app_models[(model_state.package_label, model_state.name_lower)] = (
                model_state
            )
        return cls(app_models)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ProjectState):
            return NotImplemented
        return self.models == other.models and self.real_packages == other.real_packages


class StateModelsRegistry(ModelsRegistry):
    """
    Subclass of the global Packages registry class to better handle dynamic model
    additions and removals.
    """

    def __init__(
        self,
        real_packages: set[str],
        models: dict[tuple[str, str], ModelState],
    ):
        # Any packages in self.real_packages should have all their models included
        # in the render. We don't use the original model instances as there
        # are some variables that refer to the Packages object.
        # FKs/M2Ms from real packages are also not included as they just
        # mess things up with partial states (due to lack of dependencies)
        self.real_models: list[ModelState] = []
        for package_label in real_packages:
            for model in global_models.get_models(package_label=package_label):
                self.real_models.append(ModelState.from_model(model, exclude_rels=True))

        super().__init__()  # type: ignore[misc]

        self.render_multiple([*models.values(), *self.real_models])

        self.ready = True

        # There shouldn't be any operations pending at this point.
        from plain.models.preflight import _check_lazy_references

        if errors := _check_lazy_references(self, packages_registry):
            raise ValueError("\n".join(error.message for error in errors))  # type: ignore[attr-defined]

    @contextmanager
    def bulk_update(self) -> Generator[None, None, None]:
        # Avoid clearing each model's cache for each change. Instead, clear
        # all caches when we're finished updating the model instances.
        ready = self.ready
        self.ready = False
        try:
            yield
        finally:
            self.ready = ready
            self.clear_cache()

    def render_multiple(self, model_states: list[ModelState]) -> None:
        # We keep trying to render the models in a loop, ignoring invalid
        # base errors, until the size of the unrendered models doesn't
        # decrease by at least one, meaning there's a base dependency loop/
        # missing base.
        if not model_states:
            return None
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

    def clone(self) -> StateModelsRegistry:
        """Return a clone of this registry."""
        clone = StateModelsRegistry(set(), {})
        clone.all_models = copy.deepcopy(self.all_models)

        # No need to actually clone them, they'll never change
        clone.real_models = self.real_models
        return clone

    def register_model(self, package_label: str, model: type[models.Model]) -> None:
        self.all_models[package_label][model.model_options.model_name] = model
        self.do_pending_operations(model)
        self.clear_cache()

    def unregister_model(self, package_label: str, model_name: str) -> None:
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
        self,
        package_label: str,
        name: str,
        fields: Iterable[tuple[str, Field]],
        options: dict[str, Any] | None = None,
        bases: tuple[str | type[models.Model], ...] | None = None,
    ):
        self.package_label = package_label
        self.name = name
        self.fields: dict[str, Field] = dict(fields)
        self.options = options or {}
        self.options.setdefault("indexes", [])
        self.options.setdefault("constraints", [])
        self.bases = bases or (models.Model,)
        for name, field in self.fields.items():
            # Sanity-check that fields are NOT already bound to a model.
            if hasattr(field, "model"):
                raise ValueError(
                    f'ModelState.fields cannot be bound to a model - "{name}" is.'
                )
            # Sanity-check that relation fields are NOT referring to a model class.
            if field.is_relation and hasattr(field.related_model, "_model_meta"):
                raise ValueError(
                    f'ModelState.fields cannot refer to a model class - "{name}.to" does. '
                    "Use a string reference instead."
                )
            if field.many_to_many and hasattr(
                field.remote_field.through, "_model_meta"
            ):
                raise ValueError(
                    f'ModelState.fields cannot refer to a model class - "{name}.through" '
                    "does. Use a string reference instead."
                )
        # Sanity-check that indexes have their name set.
        for index in self.options["indexes"]:
            if not index.name:  # type: ignore[attr-defined]
                raise ValueError(
                    "Indexes passed to ModelState require a name attribute. "
                    f"{index!r} doesn't have one."
                )

    @cached_property
    def name_lower(self) -> str:
        return self.name.lower()

    def get_field(self, field_name: str) -> Field:
        return self.fields[field_name]

    @classmethod
    def from_model(
        cls, model: type[models.Model], exclude_rels: bool = False
    ) -> ModelState:
        """Given a model, return a ModelState representing it."""
        # Deconstruct the fields
        fields = []
        for field in model._model_meta.local_fields:
            if getattr(field, "remote_field", None) and exclude_rels:
                continue
            name = field.name  # type: ignore[attr-defined]
            try:
                fields.append((name, field.clone()))  # type: ignore[attr-defined]
            except TypeError as e:
                raise TypeError(
                    f"Couldn't reconstruct field {name} on {model.model_options.label}: {e}"
                )
        if not exclude_rels:
            for field in model._model_meta.local_many_to_many:
                name = field.name  # type: ignore[attr-defined]
                try:
                    fields.append((name, field.clone()))  # type: ignore[attr-defined]
                except TypeError as e:
                    raise TypeError(
                        f"Couldn't reconstruct m2m field {name} on {model.model_options.object_name}: {e}"
                    )

        def flatten_bases(model: type[models.Model]) -> list[type[models.Model]]:
            bases = []
            for base in model.__bases__:
                bases.append(base)  # type: ignore[arg-type]
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
            (
                base.model_options.label_lower
                if not isinstance(base, str)
                and base is not models.Model
                and hasattr(base, "_model_meta")
                else base
            )
            for base in flattened_bases
        )
        # Ensure at least one base inherits from models.Model
        if not any(
            (isinstance(base, str) or issubclass(base, models.Model)) for base in bases
        ):
            bases = (models.Model,)

        # Construct the new ModelState
        return cls(
            model.model_options.package_label,
            model.model_options.object_name,
            fields,
            model.model_options.export_for_migrations(),
            bases,
        )

    def clone(self) -> ModelState:
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
        )

    def render(self, models_registry: ModelsRegistry) -> type[models.Model]:
        """Create a Model object from our current state into the given packages."""
        # Create Options instance with metadata
        meta_options = models.Options(
            package_label=self.package_label,
            **self.options,
        )
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
        body = {name: field.clone() for name, field in self.fields.items()}  # type: ignore[attr-defined]
        body["model_options"] = meta_options
        body["_model_meta"] = Meta(
            models_registry=models_registry
        )  # Use custom registry
        body["__module__"] = "__fake__"

        # Then, make a Model object (models_registry.register_model is called in __new__)
        model_class = type(self.name, bases, body)
        from plain.models import register_model

        # Register it to the models_registry associated with the model meta
        # (could probably do this directly right here too...)
        register_model(model_class)  # type: ignore[arg-type]

        return model_class  # type: ignore[return-value]

    def get_index_by_name(self, name: str) -> Any:
        for index in self.options["indexes"]:
            if index.name == name:  # type: ignore[attr-defined]
                return index
        raise ValueError(f"No index named {name} on model {self.name}")

    def get_constraint_by_name(self, name: str) -> Any:
        for constraint in self.options["constraints"]:
            if constraint.name == name:  # type: ignore[attr-defined]
                return constraint
        raise ValueError(f"No constraint named {name} on model {self.name}")

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: '{self.package_label}.{self.name}'>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelState):
            return NotImplemented
        return (
            (self.package_label == other.package_label)
            and (self.name == other.name)
            and (len(self.fields) == len(other.fields))
            and all(
                k1 == k2 and f1.deconstruct()[1:] == f2.deconstruct()[1:]  # type: ignore[attr-defined]
                for (k1, f1), (k2, f2) in zip(
                    sorted(self.fields.items()),
                    sorted(other.fields.items()),
                )
            )
            and (self.options == other.options)
            and (self.bases == other.bases)
        )
