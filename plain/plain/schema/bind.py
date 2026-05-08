"""Template binding for schemas.

A `BoundSchema` is the rendering side of `Schema`. It pairs a schema class
with raw input + initial values + errors so templates can read each
field's display value and error list. Use it when you need to render
schema fields in HTML — JSON paths and HTMX action paths don't need it.

The duck-typed surface matches `plain.forms.BoundField`, so existing
form templates render against `BoundSchema` unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from plain.forms.fields import Field

    from .result import Invalid, Valid
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
            # Look up by html_name first (prefix-aware), fall back to bare name
            if self.html_name in self.bound.raw:
                return self.bound.raw[self.html_name]
            return self.bound.raw.get(self.name)
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
    def from_result(
        cls,
        schema_class: type[Schema],
        result: Valid[Any] | Invalid,
        *,
        initial: dict[str, Any] | None = None,
        prefix: str | None = None,
    ) -> BoundSchema:
        """Build a BoundSchema from a `Schema.validate()` result.

        Use after a POST: validate, then bind the result for re-rendering
        with errors and the user's submitted values.
        """
        from .result import Invalid

        return cls(
            schema_class=schema_class,
            raw=result.raw,
            initial=initial or {},
            errors=result.errors if isinstance(result, Invalid) else {},
            is_bound=True,
            prefix=prefix,
        )

    @property
    def fields(self) -> dict[str, Field]:
        return self.schema_class._schema_fields

    @property
    def non_field_errors(self) -> list[str]:
        return self.errors.get("__all__", [])

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

    def __iter__(self):
        for name in self.schema_class._schema_fields:
            yield BoundField(bound=self, name=name)
