"""Preflight checks on model definitions."""

from __future__ import annotations

import inspect
import sys
import typing
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from plain.packages import packages_registry
from plain.postgres.registry import ModelsRegistry, models_registry
from plain.preflight import PreflightCheck, PreflightResult, register_check


@register_check("postgres.all_models")
class CheckAllModels(PreflightCheck):
    """Validates all model definitions for common issues."""

    def run(self) -> list[PreflightResult]:
        db_table_models = defaultdict(list)
        # Indexes and constraints share the same Postgres namespace,
        # so track them together to catch cross-type collisions.
        relation_names = defaultdict(list)
        errors = []
        models = models_registry.get_models()
        for model in models:
            db_table_models[model.model_options.db_table].append(
                model.model_options.label
            )
            if not inspect.ismethod(model.preflight):
                errors.append(
                    PreflightResult(
                        fix=f"The '{model.__name__}.preflight()' class method is currently overridden by {model.preflight!r}.",
                        obj=model,
                        id="postgres.preflight_method_overridden",
                    )
                )
            else:
                errors.extend(model.preflight())
            for model_index in model.model_options.indexes:
                relation_names[model_index.name].append(model.model_options.label)
            for model_constraint in model.model_options.constraints:
                relation_names[model_constraint.name].append(model.model_options.label)
        for db_table, model_labels in db_table_models.items():
            if len(model_labels) != 1:
                model_labels_str = ", ".join(model_labels)
                errors.append(
                    PreflightResult(
                        fix=f"db_table '{db_table}' is used by multiple models: {model_labels_str}.",
                        obj=db_table,
                        id="postgres.duplicate_db_table",
                    )
                )
        for relation_name, model_labels in relation_names.items():
            if len(model_labels) > 1:
                unique_models = set(model_labels)
                single_model = len(unique_models) == 1
                errors.append(
                    PreflightResult(
                        fix="index/constraint name '{}' is not unique {} {}.".format(
                            relation_name,
                            "for model" if single_model else "among models:",
                            ", ".join(sorted(unique_models)),
                        ),
                        id="postgres.relation_name_not_unique_single"
                        if single_model
                        else "postgres.relation_name_not_unique_multiple",
                    ),
                )
        return errors


def _carries_transform(klass: type) -> bool:
    """Whether `klass` contributes its annotated attributes to the constructor
    the type checker synthesizes -- models (via the ModelBase metaclass) and the
    mixins that inherit ModelMixin (via its own `@dataclass_transform`)."""
    from plain.postgres.base import ModelBase, ModelMixin

    return isinstance(klass, ModelBase) or issubclass(klass, ModelMixin)


def mixin_fields_hidden_from_constructor(model: type) -> list[tuple[str, str]]:
    """``(field name, mixin class name)`` for fields the runtime collects but the
    type checker can't see.

    ``Meta._create_and_cache`` walks the whole MRO for field attributes, so a
    plain-Python mixin can contribute fields to a model. PEP 681 only collects
    synthesized constructor parameters from base classes that carry the transform
    themselves, so those fields are missing from the checker's ``__init__`` and
    it rejects ``Model(that=...)`` on code the runtime accepts. Inheriting
    ``postgres.ModelMixin`` carries the transform onto the mixin and closes the
    gap -- this reports the mixins that haven't.
    """
    hidden: list[tuple[str, str]] = []
    for klass in model.__mro__:
        # Classes carrying the transform contribute their fields already.
        if _carries_transform(klass) or klass is object:
            continue
        for attr_name, attr_value in vars(klass).items():
            if attr_name.startswith("_"):
                continue
            # The same test Meta._create_and_cache uses to collect a field.
            if not inspect.isclass(attr_value) and hasattr(
                attr_value, "contribute_to_class"
            ):
                hidden.append((attr_name, klass.__name__))
    return hidden


# Deliberately NOT a registered preflight check. Every annotated, non-``ClassVar``
# attribute on a model becomes a parameter of the type checker's synthesized
# ``__init__`` (via ``@dataclass_transform`` on ``ModelBase``); if such an attribute
# isn't a real field, the checker accepts ``Model(that=...)`` while the runtime
# rejects it. Detecting that leak from raw annotations is inherently fragile
# (aliased ``ClassVar`` imports, annotated properties, string forward refs), and
# the divergence is low-harm in practice -- you have to actively construct with a
# non-field kwarg to get bitten. So rather than ship a fragile check into every
# user app's startup, we guard Plain's *own* models by running this directly from
# an internal test (tests/internal/test_typed_construction_preflight.py).
class CheckTypedConstruction(PreflightCheck):
    """Re-derives the type checker's synthesized constructor field set and
    compares it with the model's real fields in both directions.

    An annotated, non-``ClassVar`` attribute that isn't a real field *leaks* into
    the constructor -- the checker accepts ``Model(that=...)`` and the runtime
    raises. Framework metadata, custom querysets, and reverse-relation accessors
    must be annotated ``ClassVar[...]`` to stay out; real column fields and M2M
    fields (excluded via a signature-level ``init=False``) are exempt.

    A field declared on a mixin that doesn't inherit ``postgres.ModelMixin`` is
    *hidden* from the constructor -- the runtime collects it off the MRO and the
    checker rejects passing it.
    """

    def run(self) -> list[PreflightResult]:
        errors: list[PreflightResult] = []
        for model in models_registry.get_models():
            meta = model._model_meta
            # Attributes that may be annotated without ClassVar: real column
            # fields (including DB-owned init=False ones) and M2M fields.
            real = {f.name for f in meta.fields}
            real |= {f.name for f in meta.many_to_many}
            for klass in model.__mro__:
                # Only classes carrying the transform contribute synthesized
                # params -- models, and the ModelMixin subclasses they mix in.
                # Fields on a mixin without it are reported below instead.
                if not _carries_transform(klass):
                    continue
                # eval_str=False (the default) keeps string annotations as
                # strings, so forward refs are never resolved here.
                for attr, ann in inspect.get_annotations(klass).items():
                    if attr.startswith("__") or _is_classvar(ann) or attr in real:
                        continue
                    errors.append(
                        PreflightResult(
                            fix=(
                                f"'{model.__name__}.{attr}' is annotated but is not a "
                                "model field, so the type checker treats it as a "
                                f"constructor argument while the runtime rejects "
                                f"{model.__name__}({attr}=...). Annotate it "
                                "ClassVar[...] (it's a class-level accessor or "
                                "metadata, not a field) or remove the annotation."
                            ),
                            obj=model,
                            id="postgres.field_leaks_into_constructor",
                        )
                    )
            for attr, mixin in mixin_fields_hidden_from_constructor(model):
                errors.append(
                    PreflightResult(
                        fix=(
                            f"'{model.__name__}.{attr}' is a field declared on "
                            f"'{mixin}', which doesn't inherit postgres.ModelMixin, "
                            "so the type checker leaves it out of the synthesized "
                            f"constructor and rejects {model.__name__}({attr}=...) "
                            "even though the runtime accepts it. Inherit "
                            f"postgres.ModelMixin in '{mixin}'."
                        ),
                        obj=model,
                        id="postgres.field_hidden_from_constructor",
                    )
                )
        return errors


def _is_db_owned(field: Any) -> bool:
    """Whether the database, not the caller, supplies the field's value.

    These are the fields the stub declares ``init=False`` for, so they're out of
    the synthesized constructor entirely and a missing ``default=`` can't make
    them look required: the ``id``, ``create_now``/``update_now`` datetimes,
    ``generate=True`` UUIDs, and ``RandomStringField``.
    """
    return field.primary_key or field.db_returning or field.auto_fills_on_save


def nullable_fields_missing_default(model: type) -> list[str]:
    """Names of `model`'s caller-supplied ``allow_null=True`` fields whose
    declaration passed no ``default=``."""
    return [
        field.name
        for field in model._model_meta.fields  # ty: ignore[unresolved-attribute]
        if field.allow_null
        and not field.has_declared_default()
        and not _is_db_owned(field)
    ]


def nullable_default_results(model: type) -> list[PreflightResult]:
    """A warning per field `nullable_fields_missing_default` reports on `model`."""
    return [
        PreflightResult(
            fix=(
                f"'{model.__name__}.{field_name}' is allow_null=True with no "
                "declared default, so the runtime treats it as optional in the "
                f"constructor but a type checker calls {model.__name__}() a "
                "missing-argument error. Add default=None to the field to make "
                "them agree — it changes no runtime behavior and no schema."
            ),
            obj=f"{model.model_options.label}.{field_name}",  # ty: ignore[unresolved-attribute]
            id="postgres.nullable_field_without_default",
            warning=True,
        )
        for field_name in nullable_fields_missing_default(model)
    ]


@register_check("postgres.nullable_field_without_default")
class CheckNullableFieldWithoutDefault(PreflightCheck):
    """Warns about ``allow_null=True`` fields whose declaration omits ``default=``.

    The runtime already treats such a field as omittable -- ``get_default()``
    returns None for a nullable column. A type checker doesn't: PEP 681 makes a
    field optional in the synthesized constructor only when the declaration
    passes ``default=`` at the call site. So ``Model()`` runs fine and the
    checker calls the field a missing required argument. Adding ``default=None``
    settles it, and persists nothing -- None is never written as a column
    DEFAULT, so there's no migration and no schema change.
    """

    def run(self) -> list[PreflightResult]:
        results = []
        for model in models_registry.get_models():
            results.extend(nullable_default_results(model))
        return results


def _is_classvar(annotation: object) -> bool:
    """Whether `annotation` is a ``ClassVar[...]`` form.

    Annotations are strings under ``from __future__ import annotations``,
    objects otherwise -- handle both without resolving forward refs.
    """
    if isinstance(annotation, str):
        return (
            annotation.strip().strip("\"'").startswith(("ClassVar", "typing.ClassVar"))
        )
    return typing.get_origin(annotation) is typing.ClassVar


def _annotation_head(annotation: object, owner: type) -> object | None:
    """The object the annotation's outermost name refers to, or None.

    ``inspect.get_annotations`` is called with ``eval_str=False``, so under
    ``from __future__ import annotations`` every annotation arrives as a
    string. Only its *head* -- everything before the subscript -- is resolved,
    against the module that declared ``owner``. The inner reference is
    deliberately left alone: a string model reference exists precisely because
    that class isn't importable here.

    Resolving rather than string-matching is what makes an import alias
    (``from plain.postgres import Field as F``) read the same as the plain
    spelling.
    """
    if not isinstance(annotation, str):
        return typing.get_origin(annotation) or annotation

    head = annotation.strip().strip("\"'").split("[", 1)[0].strip()
    if not head:
        return None
    module = sys.modules.get(owner.__module__)
    if module is None:
        return None
    parts = head.split(".")
    resolved: Any = getattr(module, parts[0], None)
    for part in parts[1:]:
        if resolved is None:
            return None
        resolved = getattr(resolved, part, None)
    return resolved


def _annotation_names_a_field(annotation: object, owner: type) -> bool:
    """Whether `annotation` names a ``Field`` subclass -- ``Field[...]``,
    ``EncryptedField[...]``, or any alias or subclass of them."""
    from plain.postgres.fields.base import Field

    head = _annotation_head(annotation, owner)
    return isinstance(head, type) and issubclass(head, Field)


def _annotation_text(annotation: object) -> str:
    """The annotation as a reader would write it in source.

    A string annotation is used as written, minus any wrapping quotes. An
    evaluated one is named by qualname rather than ``str()``, which renders a
    class as ``<class 'app.users.models.User'>`` and would put invalid Python
    in a fix message.
    """
    if isinstance(annotation, str):
        return annotation.strip().strip("\"'").strip()
    if isinstance(annotation, type):
        return annotation.__qualname__
    if args := typing.get_args(annotation):
        return " | ".join(
            "None"
            if arg is type(None)
            else (arg.__qualname__ if isinstance(arg, type) else str(arg))
            for arg in args
        )
    return str(annotation)


def _related_type_name(annotation_text: str) -> str:
    """The related model's name, with any ``| None`` dropped.

    The fix message rebuilds the rewrite around this name and takes
    nullability from the field itself, so it never echoes a half-written
    union back at the reader.
    """
    named = [part.strip() for part in annotation_text.split("|")]
    named = [part for part in named if part and part != "None"]
    return named[0] if named else annotation_text


def foreign_keys_annotated_as_values(model: type) -> list[tuple[str, str]]:
    """``(field name, annotation)`` for `model`'s foreign keys whose class
    annotation names something other than a ``Field[...]`` form.

    An unannotated foreign key isn't reported here -- that's
    ``CheckTypedConstruction``'s story (it isn't a constructor argument at all),
    and neither is a ``ClassVar[...]`` one, which is already the declared way to
    keep an attribute out of the constructor. Only an annotation that names a
    non-Field type is a foreign key the checker reads as a model *instance*.
    """
    from plain.postgres.fields.related import ForeignKeyField

    foreign_key_names = {
        field.name
        for field in model._model_meta.fields  # ty: ignore[unresolved-attribute]
        if isinstance(field, ForeignKeyField)
    }
    if not foreign_key_names:
        return []
    # The nearest annotation in the MRO is the one a type checker reads, and
    # every class on it counts -- an ordinary Python mixin types the attribute
    # just as well as a model does. (`_carries_transform` gates the
    # *constructor* checks above, where PEP 681 really does ignore a
    # transformless base; it has nothing to say about attribute types.)
    nearest: dict[str, tuple[type, object]] = {}
    for klass in model.__mro__:
        for attr, annotation in inspect.get_annotations(klass).items():
            if attr in foreign_key_names and attr not in nearest:
                nearest[attr] = (klass, annotation)
    return sorted(
        (attr, _annotation_text(annotation))
        for attr, (klass, annotation) in nearest.items()
        if not _is_classvar(annotation)
        and not _annotation_names_a_field(annotation, klass)
    )


def foreign_key_annotation_results(model: type) -> list[PreflightResult]:
    """A warning per foreign key `foreign_keys_annotated_as_values` reports."""
    fields = {
        field.name: field
        for field in model._model_meta.fields  # ty: ignore[unresolved-attribute]
    }
    results = []
    for field_name, annotation in foreign_keys_annotated_as_values(model):
        related = _related_type_name(annotation)
        # Nullability comes from the field, not the annotation, so the message
        # always shows one rewrite that compiles.
        rewrite = f"{related} | None" if fields[field_name].allow_null else related
        nullable_note = " with default=None" if fields[field_name].allow_null else ""
        results.append(
            PreflightResult(
                fix=(
                    f"'{model.__name__}.{field_name}' is a ForeignKeyField "
                    f"annotated '{annotation}', which names a model instance "
                    "rather than a field, so a type checker sees no field there: "
                    f"class access yields a {related} instead of type[{related}], "
                    f"{model.__name__}.{field_name}.id is a plain value, and the "
                    "where() condition methods are gone. Annotate it "
                    f"'{field_name}: Field[{rewrite}] = ...'{nullable_note}, "
                    "importing the related model under `if TYPE_CHECKING:` when a "
                    "runtime import would be the cycle the string reference avoids."
                ),
                obj=f"{model.model_options.label}.{field_name}",  # ty: ignore[unresolved-attribute]
                id="postgres.foreign_key_annotated_as_value",
                warning=True,
            )
        )
    return results


@register_check("postgres.foreign_key_annotated_as_value")
class CheckForeignKeyAnnotatedAsValue(PreflightCheck):
    """Warns about a ``ForeignKeyField`` annotated with the related model itself.

    ``ForeignKeyField`` returns a descriptor that is a ``Field[V]``, and
    ``Field.__get__`` is what makes class access ``type[Related]`` (traversal)
    and instance access ``Related``. Annotating the attribute ``Related``
    instead of ``Field[Related]`` throws that away: the checker records a model
    instance, so ``Model.user`` is a ``User``, ``Model.user.id`` is an ``int``,
    and ``Model.user.id.equals(...)`` doesn't exist.

    This used to be the required spelling for a string model reference, back
    when those overloads returned a bare ``T``. They return the descriptor now,
    so ``Field[Related]`` is the one spelling for every foreign key.
    """

    def run(self) -> list[PreflightResult]:
        results = []
        for model in models_registry.get_models():
            results.extend(foreign_key_annotation_results(model))
        return results


def _check_lazy_references(
    models_registry: ModelsRegistry, packages_registry: Any
) -> list[PreflightResult]:
    """
    Ensure all lazy (i.e. string) model references have been resolved.

    Lazy references are used in various places throughout Plain, primarily in
    related fields and model signals. Identify those common cases and provide
    more helpful error messages for them.
    """
    pending_models = set(models_registry._pending_operations)

    # Short circuit if there aren't any errors.
    if not pending_models:
        return []

    def extract_operation(
        obj: Any,
    ) -> tuple[Callable[..., Any], list[Any], dict[str, Any]]:
        """
        Take a callable found in Packages._pending_operations and identify the
        original callable passed to Packages.lazy_model_operation(). If that
        callable was a partial, return the inner, non-partial function and
        any arguments and keyword arguments that were supplied with it.

        obj is a callback defined locally in Packages.lazy_model_operation() and
        annotated there with a `func` attribute so as to imitate a partial.
        """
        operation, args, keywords = obj, [], {}
        while hasattr(operation, "func"):
            args.extend(getattr(operation, "args", []))
            keywords.update(getattr(operation, "keywords", {}))
            operation = operation.func
        return operation, args, keywords

    def app_model_error(model_key: tuple[str, str]) -> str:
        try:
            packages_registry.get_package_config(model_key[0])
            model_error = "app '{}' doesn't provide model '{}'".format(*model_key)
        except LookupError:
            model_error = f"app '{model_key[0]}' isn't installed"
        return model_error

    # Here are several functions which return CheckMessage instances for the
    # most common usages of lazy operations throughout Plain. These functions
    # take the model that was being waited on as an (package_label, modelname)
    # pair, the original lazy function, and its positional and keyword args as
    # determined by extract_operation().

    def field_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult:
        error_msg = (
            "The field %(field)s was declared with a lazy reference "
            "to '%(model)s', but %(model_error)s."
        )
        params = {
            "model": ".".join(model_key),
            "field": keywords["field"],
            "model_error": app_model_error(model_key),
        }
        return PreflightResult(
            fix=error_msg % params,
            obj=keywords["field"],
            id="fields.lazy_reference_not_resolvable",
        )

    def default_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult:
        error_msg = (
            "%(op)s contains a lazy reference to %(model)s, but %(model_error)s."
        )
        params = {
            "op": func,
            "model": ".".join(model_key),
            "model_error": app_model_error(model_key),
        }
        return PreflightResult(
            fix=error_msg % params,
            obj=func,
            id="postgres.lazy_reference_resolution_failed",
        )

    # Maps common uses of lazy operations to corresponding error functions
    # defined above. If a key maps to None, no error will be produced.
    # default_error() will be used for usages that don't appear in this dict.
    known_lazy: dict[tuple[str, str], Callable[..., PreflightResult] | None] = {
        ("plain.postgres.fields.related", "resolve_related_class"): field_error,
    }

    def build_error(
        model_key: tuple[str, str],
        func: Callable[..., Any],
        args: list[Any],
        keywords: dict[str, Any],
    ) -> PreflightResult | None:
        key = (func.__module__, func.__name__)  # ty: ignore[unresolved-attribute]
        error_fn = known_lazy.get(key, default_error)
        return error_fn(model_key, func, args, keywords) if error_fn else None

    return sorted(
        filter(
            None,
            (
                build_error(model_key, *extract_operation(func))
                for model_key in pending_models
                for func in models_registry._pending_operations[model_key]
            ),
        ),
        key=lambda error: error.fix,
    )


@register_check("postgres.lazy_references")
class CheckLazyReferences(PreflightCheck):
    """Ensures all lazy (string) model references have been resolved."""

    def run(self) -> list[PreflightResult]:
        return _check_lazy_references(models_registry, packages_registry)
