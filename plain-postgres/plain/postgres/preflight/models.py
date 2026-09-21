"""Preflight checks on model definitions."""

from __future__ import annotations

import inspect
import sys
import typing
from collections import defaultdict
from collections.abc import Callable
from types import UnionType
from typing import Annotated, Any

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


# A foreign key's annotation is classified rather than parsed for meaning.
# Only positive evidence that it names the *related model* is worth a warning;
# evidence that it names a ``Field`` clears it, and everything else --
# an unresolvable name, an unfamiliar wrapper, a spelling this code has never
# seen -- is UNKNOWN and says nothing. Preflight would rather miss a wrong
# annotation than invent a rewrite nobody can use.
_FIELD = "field"
_VALUE = "value"
_UNKNOWN = "unknown"

# Wrappers are peeled one layer per pass. The cap is what keeps a self-
# referential type alias from spinning.
_MAX_UNWRAP = 10


def _brackets_balanced(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _split_top_level(text: str, separator: str) -> list[str]:
    """`text` split on `separator` outside any subscript."""
    parts: list[str] = []
    depth = 0
    current = ""
    for char in text:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if char == separator and depth == 0:
            parts.append(current.strip())
            current = ""
        else:
            current += char
    parts.append(current.strip())
    return parts


def _head_and_subscript(text: str) -> tuple[str, str | None]:
    """``("Field", "User")`` for ``"Field[User]"``; ``("User", None)`` for ``"User"``."""
    head, bracket, rest = text.partition("[")
    if not bracket or not rest.endswith("]"):
        return text.strip(), None
    return head.strip(), rest[:-1].strip()


def _string_target(text: str) -> str | None:
    """The single type a string annotation is about, or None when there isn't one.

    Peels ``Annotated[X, ...]``, ``Optional[X]``, and a top-level ``X | None``
    union. A union of two real types, an unbalanced bracket, or anything else
    this can't reduce to one name returns None -- the caller reads that as
    "can't tell".
    """
    text = text.strip().strip("\"'").strip()
    for _ in range(_MAX_UNWRAP):
        if not _brackets_balanced(text):
            return None
        members = _split_top_level(text, "|")
        if len(members) > 1:
            named = [member for member in members if member != "None"]
            if len(named) != 1:
                return None
            text = named[0]
            continue
        head, subscript = _head_and_subscript(text)
        short = head.rsplit(".", 1)[-1]
        if short == "Annotated" and subscript is not None:
            text = _split_top_level(subscript, ",")[0]
            continue
        if short == "Optional" and subscript is not None:
            text = subscript
            continue
        return text
    return None


def _unwrap_evaluated(annotation: Any) -> Any:
    """`_string_target`'s counterpart for an annotation that is a real object.

    Peels ``Annotated[...]``, ``Optional``/unions, and type aliases
    (``TypeAliasType.__value__``) down to the one type the annotation is about,
    or None when there isn't one.
    """
    for _ in range(_MAX_UNWRAP):
        origin = typing.get_origin(annotation)
        if origin is Annotated:
            # Peeled in the loop, not by recursion, so every wrapper counts
            # against the same budget -- `type Loop = Annotated[Loop, 1]` has
            # to run out of passes, not out of stack.
            annotation = typing.get_args(annotation)[0]
            continue
        if origin is typing.Union or origin is UnionType:
            named = [
                arg for arg in typing.get_args(annotation) if arg is not type(None)
            ]
            if len(named) != 1:
                return None
            annotation = named[0]
            continue
        if not isinstance(annotation, type) and hasattr(annotation, "__value__"):
            annotation = annotation.__value__
            continue
        return annotation
    return None


def _related_model(field: Any) -> type | None:
    """The model a foreign key points at, once the registry has resolved it."""
    try:
        return field.remote_field.model
    except Exception:
        return None


def _classify_annotation(annotation: object, owner: type, field: Any) -> str:
    """``_FIELD``, ``_VALUE``, or ``_UNKNOWN`` for one foreign key's annotation.

    Every step that could raise -- a module whose ``__getattr__`` objects to
    being probed, a type alias that doesn't resolve -- is caught and answers
    ``_UNKNOWN``. Preflight never tracebacks on an annotation.
    """
    try:
        return _classify(annotation, owner, field)
    except Exception:
        return _UNKNOWN


def _classify(annotation: object, owner: type, field: Any) -> str:
    from plain.postgres.base import Model
    from plain.postgres.fields.base import Field

    def by_type(candidate: object) -> str:
        if isinstance(candidate, type):
            if issubclass(candidate, Field):
                return _FIELD
            if issubclass(candidate, Model):
                return _VALUE
        return _UNKNOWN

    if not isinstance(annotation, str):
        target = _unwrap_evaluated(annotation)
        if target is None:
            return _UNKNOWN
        return by_type(typing.get_origin(target) or target)

    text = _string_target(annotation)
    if text is None:
        return _UNKNOWN
    head, subscript = _head_and_subscript(text)
    if not head:
        return _UNKNOWN

    # What the name actually refers to here beats what it looks like. A model
    # named `Field` is rare but possible, and `owner: Field` in a module where
    # `Field` is `plain.postgres.Field` means the field class either way.
    resolved = _resolve_in_module(head, owner)
    if resolved is not None:
        return by_type(resolved)

    # Nothing to resolve -- which is the normal state of affairs when the
    # related model is imported only under `if TYPE_CHECKING:`. Its own name is
    # then the only evidence there is, and this is the spelling the check
    # exists for.
    related = _related_model(field)
    if (
        subscript is None
        and related is not None
        and head.rsplit(".", 1)[-1] == (related.__name__)
    ):
        return _VALUE
    return _UNKNOWN


def _resolve_in_module(dotted: str, owner: type) -> object | None:
    """`dotted` looked up in the module that declared `owner`, or None.

    Only the annotation's head is ever looked up; the inner model reference is
    left alone, because a string model reference exists precisely because that
    class isn't importable here.
    """
    module = sys.modules.get(owner.__module__)
    if module is None:
        return None
    parts = dotted.split(".")
    resolved: Any = getattr(module, parts[0], None)
    for part in parts[1:]:
        if resolved is None:
            return None
        resolved = getattr(resolved, part, None)
    return resolved


def foreign_keys_annotated_as_values(model: type) -> list[tuple[str, str]]:
    """``(field name, related model name)`` for `model`'s foreign keys whose
    nearest annotation names the related model rather than a ``Field[...]``.

    Silent on everything it can't read with confidence: an unannotated foreign
    key (that's ``CheckTypedConstruction``'s story -- it isn't a constructor
    argument at all), a ``ClassVar[...]`` one (already the declared way to keep
    an attribute out of the constructor), and any annotation whose meaning
    isn't established.

    The returned name comes from the field, never from the annotation text, so
    the fix message can't inherit a half-parsed union or an unbalanced bracket.
    """
    from plain.postgres.fields.related import ForeignKeyField

    foreign_keys = {
        field.name: field
        for field in model._model_meta.fields  # ty: ignore[unresolved-attribute]
        if isinstance(field, ForeignKeyField)
    }
    if not foreign_keys:
        return []
    # The nearest annotation in the MRO is the one a type checker reads, and
    # every class on it counts -- an ordinary Python mixin types the attribute
    # just as well as a model does. (`_carries_transform` gates the
    # *constructor* checks above, where PEP 681 really does ignore a
    # transformless base; it has nothing to say about attribute types.)
    nearest: dict[str, tuple[type, object]] = {}
    for klass in model.__mro__:
        for attr, annotation in inspect.get_annotations(klass).items():
            if attr in foreign_keys and attr not in nearest:
                nearest[attr] = (klass, annotation)

    found: list[tuple[str, str]] = []
    for attr, (klass, annotation) in nearest.items():
        if _is_classvar(annotation):
            continue
        field = foreign_keys[attr]
        if _classify_annotation(annotation, klass, field) is not _VALUE:
            continue
        related = _related_model(field)
        if related is None:
            continue
        found.append((attr, related.__name__))
    return sorted(found)


def foreign_key_annotation_results(model: type) -> list[PreflightResult]:
    """A warning per foreign key `foreign_keys_annotated_as_values` reports."""
    fields = {
        field.name: field
        for field in model._model_meta.fields  # ty: ignore[unresolved-attribute]
    }
    results = []
    for field_name, related in foreign_keys_annotated_as_values(model):
        # Every word of the rewrite comes from the field: the related model's
        # own name, and nullability from allow_null. Nothing is echoed back
        # from the annotation, so the message can't inherit a half-parsed union
        # or an unbalanced bracket.
        allow_null = fields[field_name].allow_null
        rewrite = f"{related} | None" if allow_null else related
        nullable_note = " with default=None" if allow_null else ""
        results.append(
            PreflightResult(
                fix=(
                    f"'{model.__name__}.{field_name}' is a ForeignKeyField "
                    f"annotated as a {related}, which names a model instance "
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

    **Non-goal.** Aliasing ``Field`` to the name of a typing wrapper this reads
    structurally -- ``from plain.postgres import Field as Optional``, and then
    ``Optional[User]`` -- is classified by spelling and can warn about correct
    code. Untangling it would mean resolving names the whole point of a string
    model reference is to leave alone. The result is advisory either way:
    nothing is broken at runtime, and a stubborn one is silenceable through
    ``PREFLIGHT_SILENCED_RESULTS``.
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
