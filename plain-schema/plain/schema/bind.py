"""Template binding for schemas.

A `BoundSchema` is the rendering side of `Schema`. It pairs a schema class
with raw input + initial values + errors so templates can read each
field's display value and error list. Use it when you need to render
schema fields in HTML — JSON paths and HTMX action paths don't need it.

The duck-typed surface matches `plain.forms.BoundField`, so existing
form templates render against `BoundSchema` unchanged.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from plain.exceptions import NON_FIELD_ERRORS

from .result import Invalid

if TYPE_CHECKING:
    from .fields import Field
    from .schema import Schema

__all__ = ("BoundSchema", "BoundField")


@dataclass
class BoundField:
    """A single schema field paired with its display value and errors."""

    bound: BoundSchema
    name: str

    @property
    def field(self) -> Field:
        return self.bound.schema_class._schema_fields[self.name]

    @property
    def html_name(self) -> str:
        if self.bound.prefix:
            return f"{self.bound.prefix}-{self.name}"
        return self.name

    @property
    def html_id(self) -> str:
        return f"id_{self.html_name}"

    def value(self) -> Any:
        """Display value: raw input on bound forms (so the user sees what they
        typed even when invalid), initial otherwise."""
        if self.bound.is_bound:
            raw = self.bound.raw
            # Look up by html_name first (prefix-aware), fall back to bare name.
            key = self.html_name if self.html_name in raw else self.name
            if self.field.multi_value and hasattr(raw, "getlist"):
                # `raw` has .getlist (verified by the hasattr guard).
                return raw.getlist(key)  # ty: ignore[call-non-callable]
            return raw.get(key)
        if self.name in self.bound.initial:
            return self.bound.initial[self.name]
        return self.field.initial

    @property
    def errors(self) -> list[str]:
        return self.bound.errors.get(self.name, [])


@dataclass
class BoundSchema:
    """A schema bound to specific input/initial/error data for template rendering.

    Templates iterate it and access fields by attribute or `__getitem__`:

        {{ form.email.html_id }}
        {{ form.email.value() }}
        {% for err in form.email.errors %}{{ err }}{% endfor %}
    """

    schema_class: type[Schema]
    raw: dict[str, Any] = field(default_factory=dict)
    initial: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, list[str]] = field(default_factory=dict)
    is_bound: bool = False
    prefix: str | None = None

    @classmethod
    def from_invalid(
        cls,
        schema_class: type[Schema],
        invalid: Invalid,
        *,
        initial: dict[str, Any] | None = None,
        prefix: str | None = None,
    ) -> BoundSchema:
        """Build a BoundSchema from an `Invalid` result.

        Use after a POST that failed validation: validate, then bind the
        Invalid for re-rendering with errors and the user's submitted
        values. (The success case doesn't need a BoundSchema — the view
        redirects or renders something else.)
        """
        return cls(
            schema_class=schema_class,
            raw=invalid.raw,
            initial=initial or {},
            errors=invalid.errors,
            is_bound=True,
            prefix=prefix,
        )

    @property
    def fields(self) -> dict[str, Field]:
        return self.schema_class._schema_fields

    @property
    def non_field_errors(self) -> list[str]:
        return self.errors.get(NON_FIELD_ERRORS, [])

    def __getitem__(self, name: str) -> BoundField:
        if name not in self.schema_class._schema_fields:
            raise KeyError(name)
        return BoundField(bound=self, name=name)

    def __getattr__(self, name: str) -> BoundField:
        # Falls through to here only when normal attribute lookup fails —
        # so dataclass fields aren't shadowed.
        try:
            fields = object.__getattribute__(self, "schema_class")._schema_fields
        except AttributeError as exc:
            raise AttributeError(name) from exc
        if name in fields:
            return BoundField(bound=self, name=name)
        raise AttributeError(name)

    def __iter__(self) -> Iterator[BoundField]:
        for name in self.schema_class._schema_fields:
            yield BoundField(bound=self, name=name)
