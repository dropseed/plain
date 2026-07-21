"""Preflight checks on model definitions."""

from __future__ import annotations

import inspect
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
    """Re-derives the type checker's synthesized constructor field set and flags
    any annotated, non-``ClassVar`` attribute that isn't a real field. Framework
    metadata, custom querysets, and reverse-relation accessors must be annotated
    ``ClassVar[...]`` so they stay out of the synthesized constructor; real column
    fields and M2M fields (excluded via a signature-level ``init=False``) are exempt.
    """

    def run(self) -> list[PreflightResult]:
        import typing

        from plain.postgres.base import ModelBase

        def is_classvar(ann: object) -> bool:
            # Annotations are strings under `from __future__ import annotations`,
            # objects otherwise -- handle both without resolving forward refs.
            if isinstance(ann, str):
                return ann.lstrip().startswith(("ClassVar", "typing.ClassVar"))
            return typing.get_origin(ann) is typing.ClassVar

        errors: list[PreflightResult] = []
        for model in models_registry.get_models():
            meta = model._model_meta
            # Attributes that may be annotated without ClassVar: real column
            # fields (including DB-owned init=False ones) and M2M fields.
            real = {f.name for f in meta.fields}
            real |= {f.name for f in meta.many_to_many}
            for klass in model.__mro__:
                # Only classes carrying the transform contribute synthesized
                # params; ordinary (non-model) mixins don't.
                if not isinstance(klass, ModelBase):
                    continue
                for attr, ann in klass.__dict__.get("__annotations__", {}).items():
                    if attr.startswith("__") or is_classvar(ann) or attr in real:
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
        return errors


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
    known_lazy = {
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
