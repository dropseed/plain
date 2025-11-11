from __future__ import annotations

import copy
import warnings
from collections.abc import Iterable, Iterator, Sequence
from itertools import chain
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.models.meta import Meta
    from plain.models.options import Options

import plain.runtime
from plain.exceptions import NON_FIELD_ERRORS, ValidationError
from plain.models import models_registry, transaction
from plain.models.constants import LOOKUP_SEP
from plain.models.constraints import CheckConstraint, UniqueConstraint
from plain.models.db import (
    PLAIN_VERSION_PICKLE_KEY,
    DatabaseError,
    db_connection,
)
from plain.models.deletion import Collector
from plain.models.exceptions import (
    DoesNotExistDescriptor,
    FieldDoesNotExist,
    MultipleObjectsReturnedDescriptor,
)
from plain.models.expressions import RawSQL, Value
from plain.models.fields import NOT_PROVIDED, PrimaryKeyField
from plain.models.fields.reverse_related import ForeignObjectRel
from plain.models.meta import Meta
from plain.models.options import Options
from plain.models.query import F, Q, QuerySet
from plain.preflight import PreflightResult
from plain.utils.encoding import force_str
from plain.utils.hashable import make_hashable


class Deferred:
    def __repr__(self) -> str:
        return "<Deferred field>"

    def __str__(self) -> str:
        return "<Deferred field>"


DEFERRED = Deferred()


class ModelBase(type):
    """Metaclass for all models."""

    def __new__(
        cls, name: str, bases: tuple[type, ...], attrs: dict[str, Any], **kwargs: Any
    ) -> type:
        # Don't do any of this for the root models.Model class.
        if not bases:
            return super().__new__(cls, name, bases, attrs)

        for base in bases:
            # Models are required to directly inherit from model.Model, not a subclass of it.
            if issubclass(base, Model) and base is not Model:
                raise TypeError(
                    f"A model can't extend another model: {name} extends {base}"
                )

        return super().__new__(cls, name, bases, attrs, **kwargs)


class ModelStateFieldsCacheDescriptor:
    def __get__(
        self, instance: ModelState | None, cls: type | None = None
    ) -> ModelStateFieldsCacheDescriptor | dict[str, Any]:
        if instance is None:
            return self
        res = instance.fields_cache = {}
        return res


class ModelState:
    """Store model instance state."""

    # If true, uniqueness validation checks will consider this a new, unsaved
    # object. Necessary for correct validation of new instances of objects with
    # explicit (non-auto) PKs. This impacts validation only; it has no effect
    # on the actual save.
    adding = True
    fields_cache = ModelStateFieldsCacheDescriptor()


class Model(metaclass=ModelBase):
    # Every model gets an automatic id field
    id = PrimaryKeyField()

    # Descriptors for other model behavior
    query = QuerySet()
    model_options = Options()
    _model_meta = Meta()
    DoesNotExist = DoesNotExistDescriptor()
    MultipleObjectsReturned = MultipleObjectsReturnedDescriptor()

    def __init__(self, **kwargs: Any):
        # Alias some things as locals to avoid repeat global lookups
        cls = self.__class__
        meta = cls._model_meta
        _setattr = setattr
        _DEFERRED = DEFERRED

        # Set up the storage for instance state
        self._state = ModelState()

        # Process all fields from kwargs or use defaults
        for field in meta.fields:
            is_related_object = False
            # Virtual field
            if field.attname not in kwargs and field.column is None:
                continue
            if isinstance(field.remote_field, ForeignObjectRel):
                try:
                    # Assume object instance was passed in.
                    rel_obj = kwargs.pop(field.name)
                    is_related_object = True
                except KeyError:
                    try:
                        # Object instance wasn't passed in -- must be an ID.
                        val = kwargs.pop(field.attname)
                    except KeyError:
                        val = field.get_default()
            else:
                try:
                    val = kwargs.pop(field.attname)
                except KeyError:
                    # This is done with an exception rather than the
                    # default argument on pop because we don't want
                    # get_default() to be evaluated, and then not used.
                    # Refs #12057.
                    val = field.get_default()

            if is_related_object:
                # If we are passed a related instance, set it using the
                # field.name instead of field.attname (e.g. "user" instead of
                # "user_id") so that the object gets properly cached (and type
                # checked) by the RelatedObjectDescriptor.
                if rel_obj is not _DEFERRED:
                    _setattr(self, field.name, rel_obj)
            else:
                if val is not _DEFERRED:
                    _setattr(self, field.attname, val)

        # Handle any remaining kwargs (properties or virtual fields)
        property_names = meta._property_names
        unexpected = ()
        for prop, value in kwargs.items():
            # Any remaining kwargs must correspond to properties or virtual
            # fields.
            if prop in property_names:
                if value is not _DEFERRED:
                    _setattr(self, prop, value)
            else:
                try:
                    meta.get_field(prop)
                except FieldDoesNotExist:
                    unexpected += (prop,)
                else:
                    if value is not _DEFERRED:
                        _setattr(self, prop, value)
        if unexpected:
            unexpected_names = ", ".join(repr(n) for n in unexpected)
            raise TypeError(
                f"{cls.__name__}() got unexpected keyword arguments: {unexpected_names}"
            )

        super().__init__()

    @classmethod
    def from_db(cls, field_names: Iterable[str], values: Sequence[Any]) -> Model:
        if len(values) != len(cls._model_meta.concrete_fields):
            values_iter = iter(values)
            values = [
                next(values_iter) if f.attname in field_names else DEFERRED
                for f in cls._model_meta.concrete_fields
            ]
        # Build kwargs dict from field names and values
        field_dict = dict(
            zip((f.attname for f in cls._model_meta.concrete_fields), values)
        )
        new = cls(**field_dict)
        new._state.adding = False
        return new

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self}>"

    def __str__(self) -> str:
        return f"{self.__class__.__name__} object ({self.id})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Model):
            return NotImplemented
        if self.__class__ != other.__class__:
            return False
        my_id = self.id
        if my_id is None:
            return self is other
        return my_id == other.id

    def __hash__(self) -> int:
        if self.id is None:
            raise TypeError("Model instances without primary key value are unhashable")
        return hash(self.id)

    def __reduce__(self) -> tuple[Any, tuple[Any, ...], dict[str, Any]]:
        data = self.__getstate__()
        data[PLAIN_VERSION_PICKLE_KEY] = plain.runtime.__version__
        class_id = (
            self.model_options.package_label,
            self.model_options.object_name,
        )
        return model_unpickle, (class_id,), data

    def __getstate__(self) -> dict[str, Any]:
        """Hook to allow choosing the attributes to pickle."""
        state = self.__dict__.copy()
        state["_state"] = copy.copy(state["_state"])
        state["_state"].fields_cache = state["_state"].fields_cache.copy()
        # memoryview cannot be pickled, so cast it to bytes and store
        # separately.
        _memoryview_attrs = []
        for attr, value in state.items():
            if isinstance(value, memoryview):
                _memoryview_attrs.append((attr, bytes(value)))
        if _memoryview_attrs:
            state["_memoryview_attrs"] = _memoryview_attrs
            for attr, value in _memoryview_attrs:
                state.pop(attr)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        pickled_version = state.get(PLAIN_VERSION_PICKLE_KEY)
        if pickled_version:
            if pickled_version != plain.runtime.__version__:
                warnings.warn(
                    f"Pickled model instance's Plain version {pickled_version} does not "
                    f"match the current version {plain.runtime.__version__}.",
                    RuntimeWarning,
                    stacklevel=2,
                )
        else:
            warnings.warn(
                "Pickled model instance's Plain version is not specified.",
                RuntimeWarning,
                stacklevel=2,
            )
        if "_memoryview_attrs" in state:
            for attr, value in state.pop("_memoryview_attrs"):
                state[attr] = memoryview(value)
        self.__dict__.update(state)

    def get_deferred_fields(self) -> set[str]:
        """
        Return a set containing names of deferred fields for this instance.
        """
        return {
            f.attname
            for f in self._model_meta.concrete_fields
            if f.attname not in self.__dict__
        }

    def refresh_from_db(self, fields: list[str] | None = None) -> None:
        """
        Reload field values from the database.

        By default, the reloading happens from the database this instance was
        loaded from, or by the read router if this instance wasn't loaded from
        any database. The using parameter will override the default.

        Fields can be used to specify which fields to reload. The fields
        should be an iterable of field attnames. If fields is None, then
        all non-deferred fields are reloaded.

        When accessing deferred fields of an instance, the deferred loading
        of the field will call this method.
        """
        if fields is None:
            self._prefetched_objects_cache = {}
        else:
            prefetched_objects_cache = getattr(self, "_prefetched_objects_cache", ())
            for field in fields:
                if field in prefetched_objects_cache:
                    del prefetched_objects_cache[field]  # type: ignore[misc]
                    fields.remove(field)
            if not fields:
                return
            if any(LOOKUP_SEP in f for f in fields):
                raise ValueError(
                    f'Found "{LOOKUP_SEP}" in fields argument. Relations and transforms '
                    "are not allowed in fields."
                )

        db_instance_qs = self._model_meta.base_queryset.filter(id=self.id)

        # Use provided fields, if not set then reload all non-deferred fields.
        deferred_fields = self.get_deferred_fields()
        if fields is not None:
            fields = list(fields)
            db_instance_qs = db_instance_qs.only(*fields)
        elif deferred_fields:
            fields = [
                f.attname
                for f in self._model_meta.concrete_fields
                if f.attname not in deferred_fields
            ]
            db_instance_qs = db_instance_qs.only(*fields)

        db_instance = db_instance_qs.get()
        non_loaded_fields = db_instance.get_deferred_fields()
        for field in self._model_meta.concrete_fields:
            if field.attname in non_loaded_fields:
                # This field wasn't refreshed - skip ahead.
                continue
            setattr(self, field.attname, getattr(db_instance, field.attname))
            # Clear cached foreign keys.
            if field.is_relation and field.is_cached(self):
                field.delete_cached_value(self)

        # Clear cached relations.
        for field in self._model_meta.related_objects:
            if field.is_cached(self):
                field.delete_cached_value(self)

    def serializable_value(self, field_name: str) -> Any:
        """
        Return the value of the field name for this instance. If the field is
        a foreign key, return the id value instead of the object. If there's
        no Field object with this name on the model, return the model
        attribute's value.

        Used to serialize a field's value (in the serializer, or form output,
        for example). Normally, you would just access the attribute directly
        and not use this method.
        """
        try:
            field = self._model_meta.get_field(field_name)
        except FieldDoesNotExist:
            return getattr(self, field_name)
        return getattr(self, field.attname)

    def save(
        self,
        *,
        clean_and_validate: bool = True,
        force_insert: bool = False,
        force_update: bool = False,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """
        Save the current instance. Override this in a subclass if you want to
        control the saving process.

        The 'force_insert' and 'force_update' parameters can be used to insist
        that the "save" must be an SQL insert or update (or equivalent for
        non-SQL backends), respectively. Normally, they should not be set.
        """
        self._prepare_related_fields_for_save(operation_name="save")

        if force_insert and (force_update or update_fields):
            raise ValueError("Cannot force both insert and updating in model saving.")

        deferred_fields = self.get_deferred_fields()
        if update_fields is not None:
            # If update_fields is empty, skip the save. We do also check for
            # no-op saves later on for inheritance cases. This bailout is
            # still needed for skipping signal sending.
            if not update_fields:
                return

            update_fields = frozenset(update_fields)
            field_names = self._model_meta._non_pk_concrete_field_names
            non_model_fields = update_fields.difference(field_names)

            if non_model_fields:
                raise ValueError(
                    "The following fields do not exist in this model, are m2m "
                    "fields, or are non-concrete fields: {}".format(
                        ", ".join(non_model_fields)
                    )
                )

        # If this model is deferred, automatically do an "update_fields" save
        # on the loaded fields.
        elif not force_insert and deferred_fields:
            field_names = set()
            for field in self._model_meta.concrete_fields:
                if not field.primary_key and not hasattr(field, "through"):
                    field_names.add(field.attname)
            loaded_fields = field_names.difference(deferred_fields)
            if loaded_fields:
                update_fields = frozenset(loaded_fields)

        if clean_and_validate:
            self.full_clean(exclude=deferred_fields)

        self.save_base(
            force_insert=force_insert,
            force_update=force_update,
            update_fields=update_fields,
        )

    def save_base(
        self,
        *,
        raw: bool = False,
        force_insert: bool = False,
        force_update: bool = False,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """
        Handle the parts of saving which should be done only once per save,
        yet need to be done in raw saves, too. This includes some sanity
        checks and signal sending.

        The 'raw' argument is telling save_base not to save any parent
        models and not to do any changes to the values before save. This
        is used by fixture loading.
        """
        assert not (force_insert and (force_update or update_fields))
        assert update_fields is None or update_fields
        cls = self.__class__

        with transaction.mark_for_rollback_on_error():
            self._save_table(
                raw=raw,
                cls=cls,
                force_insert=force_insert,
                force_update=force_update,
                update_fields=update_fields,
            )
        # Once saved, this is no longer a to-be-added instance.
        self._state.adding = False

    def _save_table(
        self,
        *,
        raw: bool,
        cls: type[Model],
        force_insert: bool = False,
        force_update: bool = False,
        update_fields: Iterable[str] | None = None,
    ) -> bool:
        """
        Do the heavy-lifting involved in saving. Update or insert the data
        for a single table.
        """
        meta = cls._model_meta
        non_pks = [f for f in meta.local_concrete_fields if not f.primary_key]

        if update_fields:
            non_pks = [
                f
                for f in non_pks
                if f.name in update_fields or f.attname in update_fields
            ]

        id_val = self.id
        if id_val is None:
            id_field = meta.get_field("id")
            id_val = id_field.get_id_value_on_save(self)
            setattr(self, id_field.attname, id_val)
        id_set = id_val is not None
        if not id_set and (force_update or update_fields):
            raise ValueError("Cannot force an update in save() with no primary key.")
        updated = False
        # Skip an UPDATE when adding an instance and primary key has a default.
        if (
            not raw
            and not force_insert
            and self._state.adding
            and meta.get_field("id").default
            and meta.get_field("id").default is not NOT_PROVIDED
        ):
            force_insert = True
        # If possible, try an UPDATE. If that doesn't update anything, do an INSERT.
        if id_set and not force_insert:
            base_qs = meta.base_queryset
            values = [
                (
                    f,
                    None,
                    (getattr(self, f.attname) if raw else f.pre_save(self, False)),
                )
                for f in non_pks
            ]
            forced_update = update_fields or force_update
            updated = self._do_update(
                base_qs, id_val, values, update_fields, forced_update
            )
            if force_update and not updated:
                raise DatabaseError("Forced update did not affect any rows.")
            if update_fields and not updated:
                raise DatabaseError("Save with update_fields did not affect any rows.")
        if not updated:
            fields = meta.local_concrete_fields
            if not id_set:
                id_field = meta.get_field("id")
                fields = [f for f in fields if f is not id_field]

            returning_fields = meta.db_returning_fields
            results = self._do_insert(meta.base_queryset, fields, returning_fields, raw)
            if results:
                for value, field in zip(results[0], returning_fields):
                    setattr(self, field.attname, value)
        return updated

    def _do_update(
        self,
        base_qs: QuerySet,
        id_val: Any,
        values: list[tuple[Any, Any, Any]],
        update_fields: Iterable[str] | None,
        forced_update: bool,
    ) -> bool:
        """
        Try to update the model. Return True if the model was updated (if an
        update query was done and a matching row was found in the DB).
        """
        filtered = base_qs.filter(id=id_val)
        if not values:
            # We can end up here when saving a model in inheritance chain where
            # update_fields doesn't target any field in current model. In that
            # case we just say the update succeeded. Another case ending up here
            # is a model with just PK - in that case check that the PK still
            # exists.
            return update_fields is not None or filtered.exists()
        return filtered._update(values) > 0

    def _do_insert(
        self,
        manager: QuerySet,
        fields: Sequence[Any],
        returning_fields: Sequence[Any],
        raw: bool,
    ) -> list[Any]:
        """
        Do an INSERT. If returning_fields is defined then this method should
        return the newly created data for the model.
        """
        return manager._insert(  # type: ignore[return-value, arg-type]
            [self],
            fields=fields,  # type: ignore[arg-type]
            returning_fields=returning_fields,  # type: ignore[arg-type]
            raw=raw,
        )

    def _prepare_related_fields_for_save(
        self, operation_name: str, fields: Sequence[Any] | None = None
    ) -> None:
        # Ensure that a model instance without a PK hasn't been assigned to
        # a ForeignKey on this model. If the field is nullable, allowing the save would result in silent data loss.
        for field in self._model_meta.concrete_fields:
            if fields and field not in fields:
                continue
            # If the related field isn't cached, then an instance hasn't been
            # assigned and there's no need to worry about this check.
            if field.is_relation and field.is_cached(self):
                obj = getattr(self, field.name, None)
                if not obj:
                    continue
                # A pk may have been assigned manually to a model instance not
                # saved to the database (or auto-generated in a case like
                # UUIDField), but we allow the save to proceed and rely on the
                # database to raise an IntegrityError if applicable. If
                # constraints aren't supported by the database, there's the
                # unavoidable risk of data corruption.
                if obj.id is None:
                    # Remove the object from a related instance cache.
                    if not field.remote_field.multiple:
                        field.remote_field.delete_cached_value(obj)
                    raise ValueError(
                        f"{operation_name}() prohibited to prevent data loss due to unsaved "
                        f"related object '{field.name}'."
                    )
                elif getattr(self, field.attname) in field.empty_values:
                    # Set related object if it has been saved after an
                    # assignment.
                    setattr(self, field.name, obj)
                # If the relationship's pk/to_field was changed, clear the
                # cached relationship.
                if getattr(obj, field.target_field.attname) != getattr(
                    self, field.attname
                ):
                    field.delete_cached_value(self)

    def delete(self) -> tuple[int, dict[str, int]]:
        if self.id is None:
            raise ValueError(
                f"{self.model_options.object_name} object can't be deleted because its id attribute is set "
                "to None."
            )
        collector = Collector(origin=self)
        collector.collect([self])
        return collector.delete()

    def get_field_display(self, field_name: str) -> str:
        """Get the display value for a field, especially useful for fields with choices."""
        # Get the field object from the field name
        field = self._model_meta.get_field(field_name)
        value = getattr(self, field.attname)

        # If field has no choices, just return the value as string
        if not hasattr(field, "flatchoices") or not field.flatchoices:
            return force_str(value, strings_only=True)

        # For fields with choices, look up the display value
        choices_dict = dict(make_hashable(field.flatchoices))
        return force_str(
            choices_dict.get(make_hashable(value), value), strings_only=True
        )

    def _get_field_value_map(
        self, meta: Meta | None, exclude: set[str] | None = None
    ) -> dict[str, Value]:
        if exclude is None:
            exclude = set()
        meta = meta or self._model_meta
        return {
            field.name: Value(getattr(self, field.attname), field)
            for field in meta.local_concrete_fields
            if field.name not in exclude
        }

    def prepare_database_save(self, field: Any) -> Any:
        if self.id is None:
            raise ValueError(
                f"Unsaved model instance {self!r} cannot be used in an ORM query."
            )
        return getattr(self, field.remote_field.get_related_field().attname)

    def clean(self) -> None:
        """
        Hook for doing any extra model-wide validation after clean() has been
        called on every field by self.clean_fields. Any ValidationError raised
        by this method will not be associated with a particular field; it will
        have a special-case association with the field defined by NON_FIELD_ERRORS.
        """
        pass

    def validate_unique(self, exclude: set[str] | None = None) -> None:
        """
        Check unique constraints on the model and raise ValidationError if any
        failed.
        """
        unique_checks = self._get_unique_checks(exclude=exclude)

        if errors := self._perform_unique_checks(unique_checks):
            raise ValidationError(errors)

    def _get_unique_checks(
        self, exclude: set[str] | None = None
    ) -> list[tuple[type, tuple[str, ...]]]:
        """
        Return a list of checks to perform. Since validate_unique() could be
        called from a ModelForm, some fields may have been excluded; we can't
        perform a unique check on a model that is missing fields involved
        in that check. Fields that did not validate should also be excluded,
        but they need to be passed in via the exclude argument.
        """
        if exclude is None:
            exclude = set()
        unique_checks = []

        # Gather a list of checks for fields declared as unique and add them to
        # the list of checks.

        fields_with_class = [(self.__class__, self._model_meta.local_fields)]

        for model_class, fields in fields_with_class:
            for f in fields:
                name = f.name
                if name in exclude:
                    continue
                if f.primary_key:
                    unique_checks.append((model_class, (name,)))

        return unique_checks

    def _perform_unique_checks(
        self, unique_checks: list[tuple[type, tuple[str, ...]]]
    ) -> dict[str, list[ValidationError]]:
        errors = {}

        for model_class, unique_check in unique_checks:
            # Try to look up an existing object with the same values as this
            # object's values for all the unique field.

            lookup_kwargs = {}
            for field_name in unique_check:
                f = self._model_meta.get_field(field_name)
                lookup_value = getattr(self, f.attname)
                # TODO: Handle multiple backends with different feature flags.
                if lookup_value is None:
                    # no value, skip the lookup
                    continue
                if f.primary_key and not self._state.adding:
                    # no need to check for unique primary key when editing
                    continue
                lookup_kwargs[str(field_name)] = lookup_value

            # some fields were skipped, no reason to do the check
            if len(unique_check) != len(lookup_kwargs):
                continue

            qs = model_class.query.filter(**lookup_kwargs)  # type: ignore[attr-defined]

            # Exclude the current object from the query if we are editing an
            # instance (as opposed to creating a new one)
            # Use the primary key defined by model_class. In previous versions
            # this could differ from `self.id` due to model inheritance.
            model_class_id = getattr(self, "id")
            if not self._state.adding and model_class_id is not None:
                qs = qs.exclude(id=model_class_id)
            if qs.exists():
                if len(unique_check) == 1:
                    key = unique_check[0]
                else:
                    key = NON_FIELD_ERRORS
                errors.setdefault(key, []).append(
                    self.unique_error_message(model_class, unique_check)
                )

        return errors

    def unique_error_message(
        self, model_class: type[Model], unique_check: tuple[str, ...]
    ) -> ValidationError:
        meta = model_class._model_meta

        params = {
            "model": self,
            "model_class": model_class,
            "model_name": model_class.model_options.model_name,
            "unique_check": unique_check,
        }

        if len(unique_check) == 1:
            field = meta.get_field(unique_check[0])
            params["field_label"] = field.name
            return ValidationError(
                message=field.error_messages["unique"],
                code="unique",
                params=params,
            )
        else:
            field_names = [meta.get_field(f).name for f in unique_check]

            # Put an "and" before the last one
            field_names[-1] = f"and {field_names[-1]}"

            if len(field_names) > 2:
                # Comma join if more than 2
                params["field_label"] = ", ".join(field_names)
            else:
                # Just a space if there are only 2
                params["field_label"] = " ".join(field_names)

            # Use the first field as the message format...
            message = meta.get_field(unique_check[0]).error_messages["unique"]

            return ValidationError(
                message=message,
                code="unique",
                params=params,
            )

    def get_constraints(self) -> list[tuple[type, list[Any]]]:
        constraints = [(self.__class__, self.model_options.constraints)]
        return constraints

    def validate_constraints(self, exclude: set[str] | None = None) -> None:
        constraints = self.get_constraints()

        errors = {}
        for model_class, model_constraints in constraints:
            for constraint in model_constraints:
                try:
                    constraint.validate(model_class, self, exclude=exclude)
                except ValidationError as e:
                    if (
                        getattr(e, "code", None) == "unique"
                        and len(constraint.fields) == 1
                    ):
                        errors.setdefault(constraint.fields[0], []).append(e)
                    else:
                        errors = e.update_error_dict(errors)
        if errors:
            raise ValidationError(errors)

    def full_clean(
        self,
        *,
        exclude: set[str] | Iterable[str] | None = None,
        validate_unique: bool = True,
        validate_constraints: bool = True,
    ) -> None:
        """
        Call clean_fields(), clean(), validate_unique(), and
        validate_constraints() on the model. Raise a ValidationError for any
        errors that occur.
        """
        errors = {}
        if exclude is None:
            exclude = set()
        else:
            exclude = set(exclude)

        try:
            self.clean_fields(exclude=exclude)
        except ValidationError as e:
            errors = e.update_error_dict(errors)

        # Form.clean() is run even if other validation fails, so do the
        # same with Model.clean() for consistency.
        try:
            self.clean()
        except ValidationError as e:
            errors = e.update_error_dict(errors)

        # Run unique checks, but only for fields that passed validation.
        if validate_unique:
            for name in errors:
                if name != NON_FIELD_ERRORS and name not in exclude:
                    exclude.add(name)
            try:
                self.validate_unique(exclude=exclude)
            except ValidationError as e:
                errors = e.update_error_dict(errors)

        # Run constraints checks, but only for fields that passed validation.
        if validate_constraints:
            for name in errors:
                if name != NON_FIELD_ERRORS and name not in exclude:
                    exclude.add(name)
            try:
                self.validate_constraints(exclude=exclude)
            except ValidationError as e:
                errors = e.update_error_dict(errors)

        if errors:
            raise ValidationError(errors)

    def clean_fields(self, exclude: set[str] | None = None) -> None:
        """
        Clean all fields and raise a ValidationError containing a dict
        of all validation errors if any occur.
        """
        if exclude is None:
            exclude = set()

        errors = {}
        for f in self._model_meta.fields:
            if f.name in exclude:
                continue
            # Skip validation for empty fields with required=False. The developer
            # is responsible for making sure they have a valid value.
            raw_value = getattr(self, f.attname)
            if not f.required and raw_value in f.empty_values:
                continue
            try:
                setattr(self, f.attname, f.clean(raw_value, self))
            except ValidationError as e:
                errors[f.name] = e.error_list

        if errors:
            raise ValidationError(errors)

    @classmethod
    def preflight(cls) -> list[PreflightResult]:
        errors = []

        errors += [
            *cls._check_fields(),
            *cls._check_m2m_through_same_relationship(),
            *cls._check_long_column_names(),
        ]
        clash_errors = (
            *cls._check_id_field(),
            *cls._check_field_name_clashes(),
            *cls._check_model_name_db_lookup_clashes(),
            *cls._check_property_name_related_field_accessor_clashes(),
            *cls._check_single_primary_key(),
        )
        errors.extend(clash_errors)
        # If there are field name clashes, hide consequent column name
        # clashes.
        if not clash_errors:
            errors.extend(cls._check_column_name_clashes())
        errors += [
            *cls._check_indexes(),
            *cls._check_ordering(),
            *cls._check_constraints(),
            *cls._check_db_table_comment(),
        ]

        return errors

    @classmethod
    def _check_db_table_comment(cls) -> list[PreflightResult]:
        if not cls.model_options.db_table_comment:
            return []
        errors = []
        if not (
            db_connection.features.supports_comments
            or "supports_comments" in cls.model_options.required_db_features
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support comments on "
                    f"tables (db_table_comment).",
                    obj=cls,
                    id="models.db_table_comment_unsupported",
                    warning=True,
                )
            )
        return errors

    @classmethod
    def _check_fields(cls) -> list[PreflightResult]:
        """Perform all field checks."""
        errors = []
        for field in cls._model_meta.local_fields:
            errors.extend(field.preflight(from_model=cls))
        for field in cls._model_meta.local_many_to_many:
            errors.extend(field.preflight(from_model=cls))
        return errors

    @classmethod
    def _check_m2m_through_same_relationship(cls) -> list[PreflightResult]:
        """Check if no relationship model is used by more than one m2m field."""

        errors = []
        seen_intermediary_signatures = []

        fields = cls._model_meta.local_many_to_many

        # Skip when the target model wasn't found.
        fields = (f for f in fields if isinstance(f.remote_field.model, ModelBase))

        # Skip when the relationship model wasn't found.
        fields = (f for f in fields if isinstance(f.remote_field.through, ModelBase))

        for f in fields:
            signature = (
                f.remote_field.model,
                cls,
                f.remote_field.through,
                f.remote_field.through_fields,
            )
            if signature in seen_intermediary_signatures:
                errors.append(
                    PreflightResult(
                        fix="The model has two identical many-to-many relations "
                        f"through the intermediate model '{f.remote_field.through.model_options.label}'.",
                        obj=cls,
                        id="models.duplicate_many_to_many_relations",
                    )
                )
            else:
                seen_intermediary_signatures.append(signature)
        return errors

    @classmethod
    def _check_id_field(cls) -> list[PreflightResult]:
        """Disallow user-defined fields named ``id``."""
        if any(
            f
            for f in cls._model_meta.local_fields
            if f.name == "id" and not f.auto_created
        ):
            return [
                PreflightResult(
                    fix="'id' is a reserved word that cannot be used as a field name.",
                    obj=cls,
                    id="models.reserved_field_name_id",
                )
            ]
        return []

    @classmethod
    def _check_field_name_clashes(cls) -> list[PreflightResult]:
        """Forbid field shadowing in multi-table inheritance."""
        errors = []
        used_fields = {}  # name or attname -> field

        for f in cls._model_meta.local_fields:
            clash = used_fields.get(f.name) or used_fields.get(f.attname) or None
            # Note that we may detect clash between user-defined non-unique
            # field "id" and automatically added unique field "id", both
            # defined at the same model. This special case is considered in
            # _check_id_field and here we ignore it.
            id_conflict = (
                f.name == "id" and clash and clash.name == "id" and clash.model == cls
            )
            if clash and not id_conflict:
                errors.append(
                    PreflightResult(
                        fix=f"The field '{f.name}' clashes with the field '{clash.name}' "
                        f"from model '{clash.model.model_options}'.",
                        obj=f,
                        id="models.field_name_clash",
                    )
                )
            used_fields[f.name] = f
            used_fields[f.attname] = f

        return errors

    @classmethod
    def _check_column_name_clashes(cls) -> list[PreflightResult]:
        # Store a list of column names which have already been used by other fields.
        used_column_names = []
        errors = []

        for f in cls._model_meta.local_fields:
            _, column_name = f.get_attname_column()

            # Ensure the column name is not already in use.
            if column_name and column_name in used_column_names:
                errors.append(
                    PreflightResult(
                        fix=f"Field '{f.name}' has column name '{column_name}' that is used by "
                        "another field. Specify a 'db_column' for the field.",
                        obj=cls,
                        id="models.db_column_clash",
                    )
                )
            else:
                used_column_names.append(column_name)

        return errors

    @classmethod
    def _check_model_name_db_lookup_clashes(cls) -> list[PreflightResult]:
        errors = []
        model_name = cls.__name__
        if model_name.startswith("_") or model_name.endswith("_"):
            errors.append(
                PreflightResult(
                    fix=f"The model name '{model_name}' cannot start or end with an underscore "
                    "as it collides with the query lookup syntax.",
                    obj=cls,
                    id="models.model_name_underscore_bounds",
                )
            )
        elif LOOKUP_SEP in model_name:
            errors.append(
                PreflightResult(
                    fix=f"The model name '{model_name}' cannot contain double underscores as "
                    "it collides with the query lookup syntax.",
                    obj=cls,
                    id="models.model_name_double_underscore",
                )
            )
        return errors

    @classmethod
    def _check_property_name_related_field_accessor_clashes(
        cls,
    ) -> list[PreflightResult]:
        errors = []
        property_names = cls._model_meta._property_names
        related_field_accessors = (
            f.get_attname()
            for f in cls._model_meta._get_fields(reverse=False)
            if f.is_relation and f.related_model is not None
        )
        for accessor in related_field_accessors:
            if accessor in property_names:
                errors.append(
                    PreflightResult(
                        fix=f"The property '{accessor}' clashes with a related field "
                        "accessor.",
                        obj=cls,
                        id="models.property_related_field_clash",
                    )
                )
        return errors

    @classmethod
    def _check_single_primary_key(cls) -> list[PreflightResult]:
        errors = []
        if sum(1 for f in cls._model_meta.local_fields if f.primary_key) > 1:
            errors.append(
                PreflightResult(
                    fix="The model cannot have more than one field with "
                    "'primary_key=True'.",
                    obj=cls,
                    id="models.multiple_primary_keys",
                )
            )
        return errors

    @classmethod
    def _check_indexes(cls) -> list[PreflightResult]:
        """Check fields, names, and conditions of indexes."""
        errors = []
        references = set()
        for index in cls.model_options.indexes:
            # Index name can't start with an underscore or a number, restricted
            # for cross-database compatibility with Oracle.
            if index.name[0] == "_" or index.name[0].isdigit():
                errors.append(
                    PreflightResult(
                        fix=f"The index name '{index.name}' cannot start with an underscore "
                        "or a number.",
                        obj=cls,
                        id="models.index_name_invalid_start",
                    ),
                )
            if len(index.name) > index.max_name_length:
                errors.append(
                    PreflightResult(
                        fix="The index name '%s' cannot be longer than %d "  # noqa: UP031
                        "characters." % (index.name, index.max_name_length),
                        obj=cls,
                        id="models.index_name_too_long",
                    ),
                )
            if index.contains_expressions:
                for expression in index.expressions:
                    references.update(
                        ref[0] for ref in cls._get_expr_references(expression)
                    )
        if not (
            db_connection.features.supports_partial_indexes
            or "supports_partial_indexes" in cls.model_options.required_db_features
        ) and any(index.condition is not None for index in cls.model_options.indexes):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support indexes with conditions. "
                    "Conditions will be ignored. Silence this warning "
                    "if you don't care about it.",
                    warning=True,
                    obj=cls,
                    id="models.index_conditions_ignored",
                )
            )
        if not (
            db_connection.features.supports_covering_indexes
            or "supports_covering_indexes" in cls.model_options.required_db_features
        ) and any(index.include for index in cls.model_options.indexes):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support indexes with non-key columns. "
                    "Non-key columns will be ignored. Silence this "
                    "warning if you don't care about it.",
                    warning=True,
                    obj=cls,
                    id="models.index_non_key_columns_ignored",
                )
            )
        if not (
            db_connection.features.supports_expression_indexes
            or "supports_expression_indexes" in cls.model_options.required_db_features
        ) and any(index.contains_expressions for index in cls.model_options.indexes):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support indexes on expressions. "
                    "An index won't be created. Silence this warning "
                    "if you don't care about it.",
                    warning=True,
                    obj=cls,
                    id="models.index_on_foreign_key",
                )
            )
        fields = [
            field
            for index in cls.model_options.indexes
            for field, _ in index.fields_orders
        ]
        fields += [
            include for index in cls.model_options.indexes for include in index.include
        ]
        fields += references
        errors.extend(cls._check_local_fields(fields, "indexes"))
        return errors

    @classmethod
    def _check_local_fields(
        cls, fields: Iterable[str], option: str
    ) -> list[PreflightResult]:
        from plain.models.fields.reverse_related import ManyToManyRel

        # In order to avoid hitting the relation tree prematurely, we use our
        # own fields_map instead of using get_field()
        forward_fields_map = {}
        for field in cls._model_meta._get_fields(reverse=False):
            forward_fields_map[field.name] = field
            if hasattr(field, "attname"):
                forward_fields_map[field.attname] = field

        errors = []
        for field_name in fields:
            try:
                field = forward_fields_map[field_name]
            except KeyError:
                errors.append(
                    PreflightResult(
                        fix=f"'{option}' refers to the nonexistent field '{field_name}'.",
                        obj=cls,
                        id="models.nonexistent_field_reference",
                    )
                )
            else:
                if isinstance(field.remote_field, ManyToManyRel):
                    errors.append(
                        PreflightResult(
                            fix=f"'{option}' refers to a ManyToManyField '{field_name}', but "
                            f"ManyToManyFields are not permitted in '{option}'.",
                            obj=cls,
                            id="models.m2m_field_in_meta_option",
                        )
                    )
                elif field not in cls._model_meta.local_fields:
                    errors.append(
                        PreflightResult(
                            fix=f"'{option}' refers to field '{field_name}' which is not local to model "
                            f"'{cls.model_options.object_name}'. This issue may be caused by multi-table inheritance.",
                            obj=cls,
                            id="models.non_local_field_reference",
                        )
                    )
        return errors

    @classmethod
    def _check_ordering(cls) -> list[PreflightResult]:
        """
        Check "ordering" option -- is it a list of strings and do all fields
        exist?
        """

        if not cls.model_options.ordering:
            return []

        if not isinstance(cls.model_options.ordering, list | tuple):
            return [
                PreflightResult(
                    fix="'ordering' must be a tuple or list (even if you want to order by "
                    "only one field).",
                    obj=cls,
                    id="models.ordering_not_tuple_or_list",
                )
            ]

        errors = []
        fields = cls.model_options.ordering

        # Skip expressions and '?' fields.
        fields = (f for f in fields if isinstance(f, str) and f != "?")

        # Convert "-field" to "field".
        fields = (f.removeprefix("-") for f in fields)

        # Separate related fields and non-related fields.
        _fields = []
        related_fields = []
        for f in fields:
            if LOOKUP_SEP in f:
                related_fields.append(f)
            else:
                _fields.append(f)
        fields = _fields

        # Check related fields.
        for field in related_fields:
            _cls = cls
            fld = None
            for part in field.split(LOOKUP_SEP):
                try:
                    fld = _cls._model_meta.get_field(part)
                    if fld.is_relation:
                        _cls = fld.path_infos[-1].to_meta.model
                    else:
                        _cls = None
                except (FieldDoesNotExist, AttributeError):
                    if fld is None or (
                        fld.get_transform(part) is None and fld.get_lookup(part) is None
                    ):
                        errors.append(
                            PreflightResult(
                                fix="'ordering' refers to the nonexistent field, "
                                f"related field, or lookup '{field}'.",
                                obj=cls,
                                id="models.ordering_nonexistent_field",
                            )
                        )

        # Check for invalid or nonexistent fields in ordering.
        invalid_fields = []

        # Any field name that is not present in field_names does not exist.
        # Also, ordering by m2m fields is not allowed.
        meta = cls._model_meta
        valid_fields = set(
            chain.from_iterable(
                (f.name, f.attname)
                if not (f.auto_created and not f.concrete)
                else (f.field.related_query_name(),)
                for f in chain(meta.fields, meta.related_objects)
            )
        )

        invalid_fields.extend(set(fields) - valid_fields)

        for invalid_field in invalid_fields:
            errors.append(
                PreflightResult(
                    fix="'ordering' refers to the nonexistent field, related "
                    f"field, or lookup '{invalid_field}'.",
                    obj=cls,
                    id="models.ordering_nonexistent_field",
                )
            )
        return errors

    @classmethod
    def _check_long_column_names(cls) -> list[PreflightResult]:
        """
        Check that any auto-generated column names are shorter than the limits
        for each database in which the model will be created.
        """
        errors = []
        allowed_len = None

        max_name_length = db_connection.ops.max_name_length()
        if max_name_length is not None and not db_connection.features.truncates_names:
            allowed_len = max_name_length

        if allowed_len is None:
            return errors

        for f in cls._model_meta.local_fields:
            _, column_name = f.get_attname_column()

            # Check if auto-generated name for the field is too long
            # for the database.
            if (
                f.db_column is None
                and column_name is not None
                and len(column_name) > allowed_len
            ):
                errors.append(
                    PreflightResult(
                        fix=f'Autogenerated column name too long for field "{column_name}". '
                        f'Maximum length is "{allowed_len}" for the database. '
                        "Set the column name manually using 'db_column'.",
                        obj=cls,
                        id="models.autogenerated_column_name_too_long",
                    )
                )

        for f in cls._model_meta.local_many_to_many:
            # Skip nonexistent models.
            if isinstance(f.remote_field.through, str):
                continue

            # Check if auto-generated name for the M2M field is too long
            # for the database.
            for m2m in f.remote_field.through._model_meta.local_fields:
                _, rel_name = m2m.get_attname_column()
                if (
                    m2m.db_column is None
                    and rel_name is not None
                    and len(rel_name) > allowed_len
                ):
                    errors.append(
                        PreflightResult(
                            fix="Autogenerated column name too long for M2M field "
                            f'"{rel_name}". Maximum length is "{allowed_len}" for the database. '
                            "Use 'through' to create a separate model for "
                            "M2M and then set column_name using 'db_column'.",
                            obj=cls,
                            id="models.m2m_column_name_too_long",
                        )
                    )

        return errors

    @classmethod
    def _get_expr_references(cls, expr: Any) -> Iterator[tuple[str, ...]]:
        if isinstance(expr, Q):
            for child in expr.children:
                if isinstance(child, tuple):
                    lookup, value = child
                    yield tuple(lookup.split(LOOKUP_SEP))
                    yield from cls._get_expr_references(value)
                else:
                    yield from cls._get_expr_references(child)
        elif isinstance(expr, F):
            yield tuple(expr.name.split(LOOKUP_SEP))
        elif hasattr(expr, "get_source_expressions"):
            for src_expr in expr.get_source_expressions():
                yield from cls._get_expr_references(src_expr)

    @classmethod
    def _check_constraints(cls) -> list[PreflightResult]:
        errors = []
        if not (
            db_connection.features.supports_table_check_constraints
            or "supports_table_check_constraints"
            in cls.model_options.required_db_features
        ) and any(
            isinstance(constraint, CheckConstraint)
            for constraint in cls.model_options.constraints
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support check constraints. "
                    "A constraint won't be created. Silence this "
                    "warning if you don't care about it.",
                    obj=cls,
                    id="models.constraint_on_non_db_field",
                    warning=True,
                )
            )

        if not (
            db_connection.features.supports_partial_indexes
            or "supports_partial_indexes" in cls.model_options.required_db_features
        ) and any(
            isinstance(constraint, UniqueConstraint)
            and constraint.condition is not None
            for constraint in cls.model_options.constraints
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support unique constraints with "
                    "conditions. A constraint won't be created. Silence this "
                    "warning if you don't care about it.",
                    obj=cls,
                    id="models.constraint_on_virtual_field",
                    warning=True,
                )
            )

        if not (
            db_connection.features.supports_deferrable_unique_constraints
            or "supports_deferrable_unique_constraints"
            in cls.model_options.required_db_features
        ) and any(
            isinstance(constraint, UniqueConstraint)
            and constraint.deferrable is not None
            for constraint in cls.model_options.constraints
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support deferrable unique constraints. "
                    "A constraint won't be created. Silence this "
                    "warning if you don't care about it.",
                    obj=cls,
                    id="models.constraint_on_foreign_key",
                    warning=True,
                )
            )

        if not (
            db_connection.features.supports_covering_indexes
            or "supports_covering_indexes" in cls.model_options.required_db_features
        ) and any(
            isinstance(constraint, UniqueConstraint) and constraint.include
            for constraint in cls.model_options.constraints
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support unique constraints with non-key "
                    "columns. A constraint won't be created. Silence this "
                    "warning if you don't care about it.",
                    obj=cls,
                    id="models.constraint_on_m2m_field",
                    warning=True,
                )
            )

        if not (
            db_connection.features.supports_expression_indexes
            or "supports_expression_indexes" in cls.model_options.required_db_features
        ) and any(
            isinstance(constraint, UniqueConstraint) and constraint.contains_expressions
            for constraint in cls.model_options.constraints
        ):
            errors.append(
                PreflightResult(
                    fix=f"{db_connection.display_name} does not support unique constraints on "
                    "expressions. A constraint won't be created. Silence this "
                    "warning if you don't care about it.",
                    obj=cls,
                    id="models.constraint_on_self_referencing_fk",
                    warning=True,
                )
            )
        fields = set(
            chain.from_iterable(
                (*constraint.fields, *constraint.include)
                for constraint in cls.model_options.constraints
                if isinstance(constraint, UniqueConstraint)
            )
        )
        references = set()
        for constraint in cls.model_options.constraints:
            if isinstance(constraint, UniqueConstraint):
                if (
                    db_connection.features.supports_partial_indexes
                    or "supports_partial_indexes"
                    not in cls.model_options.required_db_features
                ) and isinstance(constraint.condition, Q):
                    references.update(cls._get_expr_references(constraint.condition))
                if (
                    db_connection.features.supports_expression_indexes
                    or "supports_expression_indexes"
                    not in cls.model_options.required_db_features
                ) and constraint.contains_expressions:
                    for expression in constraint.expressions:
                        references.update(cls._get_expr_references(expression))
            elif isinstance(constraint, CheckConstraint):
                if (
                    db_connection.features.supports_table_check_constraints
                    or "supports_table_check_constraints"
                    not in cls.model_options.required_db_features
                ):
                    if isinstance(constraint.check, Q):
                        references.update(cls._get_expr_references(constraint.check))
                    if any(
                        isinstance(expr, RawSQL) for expr in constraint.check.flatten()
                    ):
                        errors.append(
                            PreflightResult(
                                fix=f"Check constraint {constraint.name!r} contains "
                                f"RawSQL() expression and won't be validated "
                                f"during the model full_clean(). "
                                "Silence this warning if you don't care about it.",
                                warning=True,
                                obj=cls,
                                id="models.constraint_name_collision_autogenerated",
                            ),
                        )
        for field_name, *lookups in references:
            fields.add(field_name)
            if not lookups:
                # If it has no lookups it cannot result in a JOIN.
                continue
            try:
                field = cls._model_meta.get_field(field_name)
                if not field.is_relation or field.many_to_many or field.one_to_many:
                    continue
            except FieldDoesNotExist:
                continue
            # JOIN must happen at the first lookup.
            first_lookup = lookups[0]
            if (
                hasattr(field, "get_transform")
                and hasattr(field, "get_lookup")
                and field.get_transform(first_lookup) is None
                and field.get_lookup(first_lookup) is None
            ):
                errors.append(
                    PreflightResult(
                        fix=f"'constraints' refers to the joined field '{LOOKUP_SEP.join([field_name] + lookups)}'.",
                        obj=cls,
                        id="models.constraint_refers_to_joined_field",
                    )
                )
        errors.extend(cls._check_local_fields(fields, "constraints"))
        return errors


########
# MISC #
########


def model_unpickle(model_id: tuple[str, str] | type[Model]) -> Model:
    """Used to unpickle Model subclasses with deferred fields."""
    if isinstance(model_id, tuple):
        model = models_registry.get_model(*model_id)
    else:
        # Backwards compat - the model was cached directly in earlier versions.
        model = model_id
    return model.__new__(model)


model_unpickle.__safe_for_unpickle__ = True  # type: ignore[attr-defined]
