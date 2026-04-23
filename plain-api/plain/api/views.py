import datetime
from functools import cached_property
from http.client import responses as http_status_phrases
from typing import Any

from plain.exceptions import ValidationError
from plain.forms.exceptions import FormFieldMissingError
from plain.http import (
    HTTPException,
    JsonResponse,
    NotFoundError404,
    Response,
    ResponseBase,
)
from plain.utils import timezone
from plain.utils.cache import patch_cache_control
from plain.views.base import View
from plain.views.exceptions import ResponseException

from . import openapi
from .schemas import ErrorSchema

# Allow plain.api to be used without plain.postgres
try:
    from .models import APIKey
except ImportError:
    APIKey: Any = None

__all__ = [
    "APIKeyView",
    "APIResult",
    "APIView",
]

type APIResult = (
    ResponseBase
    | int
    | None
    | dict[str, Any]
    | list[Any]
    | tuple[int, dict[str, Any] | list[Any]]
)


def _error_response(*, error_id: str, message: str, status_code: int) -> JsonResponse:
    return JsonResponse(
        ErrorSchema(id=error_id, message=message, url=""),
        status_code=status_code,
    )


# Snake-case ids are part of the public API surface — client libs key off them.
_STATUS_ERROR_IDS = {
    400: "bad_request",
    401: "unauthorized",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    429: "rate_limited",
}


# @openapi.response_typed_dict(400, ErrorSchema)
# @openapi.response_typed_dict(401, ErrorSchema)
class APIKeyView(View):
    api_key_required = True

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

    def after_response(self, response: ResponseBase) -> ResponseBase:
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
                api_key = APIKey.query.get(token=header_token)  # ty: ignore[unresolved-attribute]
            except APIKey.DoesNotExist:  # ty: ignore[unresolved-attribute]
                raise ResponseException(
                    _error_response(
                        error_id="invalid_api_token",
                        message="Invalid API token",
                        status_code=400,
                    )
                )

            if api_key.expires_at and api_key.expires_at < datetime.datetime.now():
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
class APIView(View):
    def convert_value_to_response(self, value: APIResult) -> ResponseBase:
        if isinstance(value, ResponseBase):
            return value

        if value is None:
            raise NotFoundError404

        if isinstance(value, int):
            return Response(status_code=value)

        status_code = 200

        if isinstance(value, tuple):
            if len(value) != 2:
                raise ValueError(
                    "Tuple response must be of length 2 (status_code, value)"
                )
            status_code, value = value

        if isinstance(value, dict):
            return JsonResponse(value, status_code=status_code)

        if isinstance(value, list):
            return JsonResponse(value, status_code=status_code, safe=False)

        raise TypeError(f"Unexpected APIView return type: {type(value).__name__}")

    def handle_exception(self, exc: Exception) -> ResponseBase:
        if isinstance(exc, ValidationError):
            return _error_response(
                error_id="validation_error",
                message=f"Validation error: {exc.message}",
                status_code=400,
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
