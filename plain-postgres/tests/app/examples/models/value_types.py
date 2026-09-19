"""Fixtures for `value_type=` columns.

`Slug` and `Coordinates` are deliberately trivial value types — the point is
the round trip through the column and the refusal of anything that isn't one,
not the behavior they wrap.
"""

from __future__ import annotations

from typing import Any, Self

from plain.postgres import Field, types

from plain import postgres


class Slug:
    """A text value type: stored as the slug string itself."""

    def __init__(self, text: str) -> None:
        self.text = text

    @classmethod
    def from_db(cls, raw: Any, /) -> Self:
        return cls(raw)

    def to_db(self) -> str:
        return self.text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Slug):
            return NotImplemented
        return self.text == other.text

    def __hash__(self) -> int:
        return hash(self.text)

    def __repr__(self) -> str:
        return f"Slug({self.text!r})"


class Coordinates:
    """A JSON value type: stored as a two-key object."""

    def __init__(self, lat: float, lon: float) -> None:
        self.lat = lat
        self.lon = lon

    @classmethod
    def from_db(cls, raw: Any, /) -> Self:
        return cls(raw["lat"], raw["lon"])

    def to_db(self) -> dict[str, float]:
        return {"lat": self.lat, "lon": self.lon}

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Coordinates):
            return NotImplemented
        return (self.lat, self.lon) == (other.lat, other.lon)

    def __hash__(self) -> int:
        return hash((self.lat, self.lon))

    def __repr__(self) -> str:
        return f"Coordinates({self.lat!r}, {self.lon!r})"


@postgres.register_model
class ValueTypeExample(postgres.Model):
    name: Field[str] = types.TextField(max_length=50)
    slug: Field[Slug] = types.TextField(value_type=Slug)
    location: Field[Coordinates | None] = types.JSONField(
        value_type=Coordinates, required=False, allow_null=True, default=None
    )
