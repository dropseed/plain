from __future__ import annotations

import zoneinfo
from functools import cache
from typing import TYPE_CHECKING, Any

from plain import exceptions

from . import Field

if TYPE_CHECKING:
    from plain.models.base import Model


@cache
def _get_canonical_timezones() -> frozenset[str]:
    """
    Get canonical IANA timezone names, excluding deprecated legacy aliases.

    Filters out legacy timezone names like US/Central, Canada/Eastern, etc.
    that are backward compatibility aliases. These legacy names can cause
    issues with databases like PostgreSQL that only recognize canonical names.
    """
    all_zones = zoneinfo.available_timezones()

    # Known legacy prefixes (deprecated in favor of Area/Location format)
    legacy_prefixes = ("US/", "Canada/", "Brazil/", "Chile/", "Mexico/")

    # Obsolete timezone abbreviations
    obsolete_zones = {
        "EST",
        "MST",
        "HST",
        "EST5EDT",
        "CST6CDT",
        "MST7MDT",
        "PST8PDT",
    }

    # Filter to only canonical timezone names
    return frozenset(
        tz
        for tz in all_zones
        if not tz.startswith(legacy_prefixes) and tz not in obsolete_zones
    )


class TimeZoneField(Field[zoneinfo.ZoneInfo]):
    """
    A model field that stores timezone names as strings but provides ZoneInfo objects.

    Similar to DateField which stores dates but provides datetime.date objects,
    this field stores timezone strings (e.g., "America/Chicago") but provides
    zoneinfo.ZoneInfo objects when accessed.
    """

    description = "A timezone (stored as string, accessed as ZoneInfo)"

    # Mapping of legacy timezone names to canonical IANA names
    # Based on IANA timezone database backward compatibility file
    LEGACY_TO_CANONICAL = {
        "US/Alaska": "America/Anchorage",
        "US/Aleutian": "America/Adak",
        "US/Arizona": "America/Phoenix",
        "US/Central": "America/Chicago",
        "US/East-Indiana": "America/Indiana/Indianapolis",
        "US/Eastern": "America/New_York",
        "US/Hawaii": "Pacific/Honolulu",
        "US/Indiana-Starke": "America/Indiana/Knox",
        "US/Michigan": "America/Detroit",
        "US/Mountain": "America/Denver",
        "US/Pacific": "America/Los_Angeles",
        "US/Samoa": "Pacific/Pago_Pago",
    }

    def __init__(self, **kwargs: Any):
        kwargs.setdefault("max_length", 100)
        kwargs.setdefault("choices", self._get_timezone_choices())
        super().__init__(**kwargs)

    def _get_timezone_choices(self) -> list[tuple[str, str]]:
        """Get timezone choices for form widgets."""
        zones = [(tz, tz) for tz in _get_canonical_timezones()]
        zones.sort(key=lambda x: x[1])
        return [("", "---------")] + zones

    def get_internal_type(self) -> str:
        return "CharField"

    def to_python(self, value: Any) -> zoneinfo.ZoneInfo | None:
        """Convert input to ZoneInfo object."""
        if value is None or value == "":
            return None
        if isinstance(value, zoneinfo.ZoneInfo):
            return value
        try:
            return zoneinfo.ZoneInfo(value)
        except zoneinfo.ZoneInfoNotFoundError:
            raise exceptions.ValidationError(
                f"'{value}' is not a valid timezone.",
                code="invalid",
                params={"value": value},
            )

    def from_db_value(
        self, value: Any, expression: Any, connection: Any
    ) -> zoneinfo.ZoneInfo | None:
        """Convert database value to ZoneInfo object."""
        if value is None or value == "":
            return None
        # Normalize legacy timezone names
        value = self.LEGACY_TO_CANONICAL.get(value, value)
        return zoneinfo.ZoneInfo(value)

    def get_prep_value(self, value: Any) -> str | None:
        """Convert ZoneInfo to string for database storage."""
        if value is None:
            return None
        if isinstance(value, zoneinfo.ZoneInfo):
            value = str(value)
        # Normalize legacy timezone names before saving
        return self.LEGACY_TO_CANONICAL.get(value, value)

    def value_to_string(self, obj: Model) -> str:
        """Serialize value for fixtures/migrations."""
        value = self.value_from_object(obj)
        prep_value = self.get_prep_value(value)
        return prep_value if prep_value is not None else ""

    def validate(self, value: Any, model_instance: Model) -> None:
        """Validate value against choices using string comparison."""
        # Convert ZoneInfo to string for choice validation since choices are strings
        if isinstance(value, zoneinfo.ZoneInfo):
            value = str(value)
        return super().validate(value, model_instance)
