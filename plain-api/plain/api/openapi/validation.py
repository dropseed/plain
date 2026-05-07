from __future__ import annotations

from typing import Any


class OpenAPIValidationError(Exception):
    """Raised when an OpenAPI schema fails structural validation."""


def validate_openapi_schema(schema: dict[str, Any]) -> None:
    """Validate a generated OpenAPI document against the OpenAPI specification.

    Uses ``openapi-spec-validator`` to detect the spec version (3.0.x or 3.1.x)
    and run the appropriate JSON Schema validation locally — no network calls.
    """
    try:
        from openapi_spec_validator import validate
        from openapi_spec_validator.validation.exceptions import (
            OpenAPIValidationError as _UpstreamValidationError,
        )
        from referencing.exceptions import Unresolvable
    except ImportError as exc:
        raise OpenAPIValidationError(
            "openapi-spec-validator is required for --validate. "
            "Install it with: pip install openapi-spec-validator"
        ) from exc

    try:
        validate(schema)
    except (_UpstreamValidationError, Unresolvable) as exc:
        raise OpenAPIValidationError(str(exc)) from exc
