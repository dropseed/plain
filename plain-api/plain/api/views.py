from collections.abc import Mapping
from functools import cached_property
from http.client import responses as http_status_phrases
from typing import Any, cast

from plain.exceptions import ValidationError
from plain.forms.exceptions import FormFieldMissingError
from plain.http import (
    HTTPException,
    JsonResponse,
    NotFoundError404,
    Response,
)
from plain.utils import timezone
from plain.utils.cache import patch_cache_control
from plain.views.base import View
from plain.views.exceptions import ResponseException

from . import openapi
from .schemas import ErrorSchema, FieldError

# Allow plain.api to be used without plain.postgres
try:
    from .models import APIKey
except ImportError:
    APIKey: Any = None

__all__ = [
    "APIKeyView",
    "APIResult",
    "APIView",
    "JsonNotFoundView",
]

# `Mapping[str, Any]` (vs `dict[str, Any]`) lets `def get(self) -> MyTypedDict:`
# satisfy Liskov against the base view — TypedDicts aren't `dict` per PEP 589.
type APIResult = (
    Response
    | None
    | Mapping[str, Any]
    | list[Any]
    | tuple[int, dict[str, Any] | list[Any]]
)


def _error_response(
    *,
    error_id: str,
    message: str,
    status_code: int,
    errors: list[FieldError] | None = None,
) -> JsonResponse:
    body: ErrorSchema = {"id": error_id, "message": message}
    if errors is not None:
        body["errors"] = errors
    return JsonResponse(body, status_code=status_code)


def _validation_field_errors(exc: ValidationError) -> list[FieldError] | None:
    """Flatten a field-dict ValidationError into a list of `{field, message}`.

    Returns None for string- or list-shaped errors that have no field context.
    """
    if not hasattr(exc, "error_dict"):
        return None
    return [
        {"field": field, "message": message}
        for field, messages in exc
        for message in messages
    ]


# Snake-case ids are part of the public API surface — client libs key off them.
_STATUS_ERROR_IDS = {
    400: "bad_request",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    429: "rate_limited",
}


# @openapi.response_typed_dict(400, ErrorSchema)
# @openapi.response_typed_dict(401, ErrorSchema)
class APIKeyView(View[APIResult]):
    api_key_required = True

    # Picked up by the OpenAPI generator: each entry is added to
    # `components.securitySchemes` and required on every operation served by
    # this view. Subclasses can override to declare a different scheme.
    openapi_security_schemes: dict[str, dict[str, Any]] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
        }
    }

    @cached_property
    def api_key(self) -> Any:
        return self.get_api_key()

    def before_request(self) -> None:
        if self.api_key:
            self.use_api_key()
        elif self.api_key_required:
            raise ResponseException(
                _error_response(
                    error_id="api_key_required",
                    message="API key required",
                    status_code=401,
                )
            )

    def after_response(self, response: Response) -> Response:
        response = super().after_response(response)
        # Make sure it at least has private as a default
        patch_cache_control(response, private=True)
        return response

    def use_api_key(self) -> None:
        """
        Use the API key for this request.

        Override this to perform other actions with a valid API key.
        """
        self.api_key.last_used_at = timezone.now()
        self.api_key.save(update_fields=["last_used_at"])

    def get_api_key(self) -> Any:
        """
        Get the API key from the request.

        Override this if you want to use a different input method.
        """
        if "Authorization" in self.request.headers:
            header_value = self.request.headers["Authorization"]
            try:
                header_token = header_value.split("Bearer ")[1]
            except IndexError:
                raise ResponseException(
                    _error_response(
                        error_id="invalid_authorization_header",
                        message="Invalid Authorization header",
                        status_code=400,
                    )
                )

            try:
                api_key = APIKey.query.get(token=header_token)
            except APIKey.DoesNotExist:
                raise ResponseException(
                    _error_response(
                        error_id="invalid_api_token",
                        message="Invalid API token",
                        status_code=400,
                    )
                )

            if api_key.is_expired():
                raise ResponseException(
                    _error_response(
                        error_id="api_token_expired",
                        message="API token has expired",
                        status_code=400,
                    )
                )

            return api_key


@openapi.response_typed_dict(400, ErrorSchema, component_name="BadRequest")
@openapi.response_typed_dict(401, ErrorSchema, component_name="Unauthorized")
@openapi.response_typed_dict(403, ErrorSchema, component_name="Forbidden")
@openapi.response_typed_dict(404, ErrorSchema, component_name="NotFound")
@openapi.response_typed_dict(
    "5XX", ErrorSchema, description="Unexpected Error", component_name="ServerError"
)
class APIView(View[APIResult]):
    def convert_result_to_response(self, result: APIResult) -> Response:
        if isinstance(result, Response):
            return result

        if result is None:
            raise NotFoundError404

        status_code = 200

        if isinstance(result, tuple):
            if len(result) != 2:
                raise ValueError(
                    "Tuple response must be of length 2 (status_code, data)"
                )
            status_code, result = cast(tuple[int, dict[str, Any] | list[Any]], result)

        if isinstance(result, dict):
            return JsonResponse(result, status_code=status_code)

        if isinstance(result, list):
            return JsonResponse(result, status_code=status_code, safe=False)

        raise TypeError(f"Unexpected APIView return type: {type(result).__name__}")

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, ValidationError):
            errors = _validation_field_errors(exc)
            if errors is not None:
                message = "Validation error"
            else:
                detail = "; ".join(exc.messages) if exc.messages else str(exc)
                message = f"Validation error: {detail}"
            return _error_response(
                error_id="validation_error",
                message=message,
                status_code=400,
                errors=errors,
            )
        if isinstance(exc, FormFieldMissingError):
            return _error_response(
                error_id="missing_field",
                message=f"Missing field: {exc.field_name}",
                status_code=400,
            )
        if isinstance(exc, HTTPException):
            error_id = _STATUS_ERROR_IDS.get(exc.status_code, "http_error")
            return _error_response(
                error_id=error_id,
                message=str(exc)
                or http_status_phrases.get(exc.status_code, "HTTP error"),
                status_code=exc.status_code,
            )
        return _error_response(
            error_id="server_error",
            message="Internal server error",
            status_code=500,
        )


class JsonNotFoundView(APIView):
    """Catch-all view that always returns a JSON 404.

    Mount as a regex catch-all at the end of an API router so unmatched
    paths under your API prefix return a JSON `ErrorSchema` body instead of
    the framework's HTML 404 page.
    """

    def before_request(self) -> None:
        raise NotFoundError404
