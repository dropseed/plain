"""Preflight checks for index coverage on app models."""

from __future__ import annotations

from typing import Any

from plain.packages import packages_registry
from plain.postgres.constraints import UniqueConstraint
from plain.postgres.expressions import F, OrderBy
from plain.postgres.fields.related import ForeignKeyField
from plain.postgres.query_utils import Q
from plain.postgres.registry import models_registry
from plain.preflight import PreflightCheck, PreflightResult, register_check


def _get_app_models() -> list[Any]:
    """Return models from the user's app packages only (not framework/third-party)."""
    app_models = []
    for package_config in packages_registry.get_package_configs():
        if package_config.name.startswith("app."):
            app_models.extend(
                models_registry.get_models(package_label=package_config.package_label)
            )
    return app_models


def _collect_model_indexes(model: Any) -> list[tuple[str, list[str], bool]]:
    """Collect (name, fields, is_unique) for non-partial indexes/constraints.

    Partials are skipped: they only apply to rows matching their predicate,
    so they're never interchangeable with a full index for duplicate
    detection or reorder suggestions.
    """
    all_indexes: list[tuple[str, list[str], bool]] = []

    for index in model.model_options.indexes:
        if index.fields and not index.is_partial:
            fields = [f.lstrip("-") for f in index.fields]
            all_indexes.append((index.name, fields, False))

    for constraint in model.model_options.constraints:
        if (
            isinstance(constraint, UniqueConstraint)
            and constraint.fields
            and not constraint.is_partial
        ):
            all_indexes.append((constraint.name, list(constraint.fields), True))

    return all_indexes


def _bare_column_name(expr: Any) -> str | None:
    """Return the column name if `expr` resolves to a bare column, else `None`.

    Postgres can range-scan the leading column of an index for `WHERE col = ?`
    only when that column is a real attribute, not an expression — so a
    compound leading expression like `Lower("email")` returns `None` here.
    Sort direction (`F("col").desc()` / `OrderBy(F)`) doesn't affect equality
    lookups, so we unwrap one layer of `OrderBy` around a bare `F`.
    """
    if isinstance(expr, OrderBy):
        expr = expr.expression
    if isinstance(expr, F):
        return expr.name
    return None


def _leading_field_name(
    fields: tuple[str, ...] | list[str], expressions: tuple
) -> str | None:
    """The leading column's field name, or `None` if it's an expression."""
    if fields:
        return fields[0].lstrip("-")
    if expressions:
        return _bare_column_name(expressions[0])
    return None


def _condition_is_not_null_on(condition: Q, field_name: str) -> bool:
    """True if `condition` is exactly ``Q(<field_name>__isnull=False)``."""
    return (
        not condition.negated
        and len(condition.children) == 1
        and condition.children[0] == (f"{field_name}__isnull", False)
    )


def _fk_covered_field_names(model: Any) -> set[str]:
    """Field names that appear as the leading column of an index or unique
    constraint — covering arbitrary FK lookups via the index's leading
    column. Includes expression-based indexes/constraints whose leading
    expression is a bare ``F(field_name)``.

    Partial indexes/constraints (declared with ``condition=Q(...)``) are
    excluded: Postgres can only use them for queries whose predicate
    implies the partial-index predicate, so an FK lookup or cascade
    delete that doesn't filter by that condition still does a sequential
    scan. The one exception is a predicate of exactly
    ``Q(<fk>__isnull=False)`` on the leading FK itself — every FK lookup
    and referencing-side sweep is a ``WHERE fk = ?``, which implies
    ``fk IS NOT NULL``, so Postgres can always use that partial. Match
    the doctor's coverage rule in
    ``introspection/health/checks_structural.py``.
    """
    covered: set[str] = set()

    def _record(index_or_constraint: Any) -> None:
        leading = _leading_field_name(
            index_or_constraint.fields, index_or_constraint.expressions
        )
        if leading is None:
            return
        if not index_or_constraint.is_partial or _condition_is_not_null_on(
            index_or_constraint.condition, leading
        ):
            covered.add(leading)

    for index in model.model_options.indexes:
        _record(index)

    for constraint in model.model_options.constraints:
        if isinstance(constraint, UniqueConstraint):
            _record(constraint)

    return covered


def _composite_containing(model: Any, field_name: str) -> tuple[str, list[str]] | None:
    """First non-partial index/constraint with `field_name` at a non-leading position.

    A non-leading column doesn't cover the FK, but reordering the composite to
    lead with it often can — worth suggesting in the fix message.
    """
    for name, fields, _is_unique in _collect_model_indexes(model):
        if field_name in fields[1:]:
            return name, fields
    return None


@register_check("postgres.missing_fk_indexes")
class CheckMissingFKIndexes(PreflightCheck):
    """Warns about foreign key fields without index coverage."""

    def run(self) -> list[PreflightResult]:
        results = []

        for model in _get_app_models():
            covered_fields = _fk_covered_field_names(model)

            for field in model._model_meta.local_fields:
                if (
                    isinstance(field, ForeignKeyField)
                    and not field.primary_key
                    and field.name not in covered_fields
                ):
                    fix = (
                        f"Foreign key '{field.name}' has no index coverage. "
                        f"Add an Index on [\"{field.name}\"] or a constraint with '{field.name}' as the first field."
                    )

                    if composite := _composite_containing(model, field.name):
                        composite_name, composite_fields = composite
                        fix += (
                            f" Alternatively, '{composite_name}' on [{', '.join(composite_fields)}] "
                            f"already includes '{field.name}' — reordering it to put '{field.name}' first "
                            f"covers this FK without a new index (safe when every query using it "
                            f"filters all of its columns with equality)."
                        )

                    results.append(
                        PreflightResult(
                            fix=fix,
                            obj=f"{model.model_options.label}.{field.name}",
                            id="postgres.missing_fk_index",
                            warning=True,
                        )
                    )

        return results


@register_check("postgres.duplicate_indexes")
class CheckDuplicateIndexes(PreflightCheck):
    """Warns about indexes redundant with other indexes or constraints.

    Catches both prefix-redundancy (a 1-column index shadowed by a wider
    composite) and exact-column duplicates (an `Index(fields=["x"])` that
    duplicates a same-column `UniqueConstraint`).
    """

    def run(self) -> list[PreflightResult]:
        results = []

        for model in _get_app_models():
            all_indexes = _collect_model_indexes(model)

            flagged: set[str] = set()
            for i, idx_a in enumerate(all_indexes):
                for idx_b in all_indexes[i + 1 :]:
                    for shorter, longer in [(idx_a, idx_b), (idx_b, idx_a)]:
                        s_name, s_fields, s_unique = shorter
                        l_name, l_fields, l_unique = longer

                        if s_name in flagged:
                            continue

                        is_prefix_dup = (
                            not s_unique
                            and len(s_fields) < len(l_fields)
                            and l_fields[: len(s_fields)] == s_fields
                        )
                        is_exact_dup = (
                            s_fields == l_fields
                            and not s_unique
                            and (l_unique or s_name > l_name)
                        )

                        if not (is_prefix_dup or is_exact_dup):
                            continue

                        if is_prefix_dup:
                            fix = (
                                f"Index '{s_name}' on [{', '.join(s_fields)}] "
                                f"is redundant with '{l_name}' on [{', '.join(l_fields)}]. "
                                f"The longer index covers the same queries."
                            )
                        elif l_unique:
                            fix = (
                                f"Index '{s_name}' on [{', '.join(s_fields)}] "
                                f"is redundant with '{l_name}' on the same columns. "
                                f"The unique-backed index already covers these queries."
                            )
                        else:
                            fix = (
                                f"Index '{s_name}' on [{', '.join(s_fields)}] "
                                f"is an exact duplicate of '{l_name}'. "
                                f"Drop one of them."
                            )

                        results.append(
                            PreflightResult(
                                fix=fix,
                                obj=model.model_options.label,
                                id="postgres.duplicate_index",
                                warning=True,
                            )
                        )
                        flagged.add(s_name)

        return results
