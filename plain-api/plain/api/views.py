import datetime
import logging
from functools import cached_property
from typing import Any

from plain.exceptions import ValidationError
from plain.forms.exceptions import FormFieldMissingError
from plain.http import ForbiddenError403, JsonResponse, NotFoundError404, ResponseBase
from plain.runtime import settings
from plain.utils import timezone
from plain.utils.cache import patch_cache_control
from plain.views.base import View
from plain.views.exceptions import ResponseException

from . import openapi
from .schemas import ErrorSchema

# Allow plain.api to be used without plain.models
try:
    from .models import APIKey, DeviceGrant
except ImportError:
    APIKey = None  # type: ignore[misc, assignment]
    DeviceGrant = None  # type: ignore[misc, assignment]

__all__ = [
    "APIKeyView",
    "APIView",
    "DeviceAuthorizeView",
    "DeviceTokenView",
]

logger = logging.getLogger("plain.api")


# @openapi.response_typed_dict(400, ErrorSchema)
# @openapi.response_typed_dict(401, ErrorSchema)
class APIKeyView(View):
    api_key_required = True

    @cached_property
    def api_key(self) -> Any:
        return self.get_api_key()

    def get_response(self) -> ResponseBase:
        if self.api_key:
            self.use_api_key()
        elif self.api_key_required:
            return JsonResponse(
                ErrorSchema(
                    id="api_key_required",
                    message="API key required",
                    url="",
                ),
                status_code=401,
            )

        response = super().get_response()
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
                    JsonResponse(
                        ErrorSchema(
                            id="invalid_authorization_header",
                            message="Invalid Authorization header",
                            url="",
                        ),
                        status_code=400,
                    )
                )

            try:
                api_key = APIKey.query.get(token=header_token)
            except APIKey.DoesNotExist:
                raise ResponseException(
                    JsonResponse(
                        ErrorSchema(
                            id="invalid_api_token",
                            message="Invalid API token",
                            url="",
                        ),
                        status_code=400,
                    )
                )

            if api_key.expires_at and api_key.expires_at < datetime.datetime.now():
                raise ResponseException(
                    JsonResponse(
                        ErrorSchema(
                            id="api_token_expired",
                            message="API token has expired",
                            url="",
                        ),
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
    def get_response(self) -> ResponseBase:
        try:
            return super().get_response()
        except ResponseException as e:
            # Catch any response exceptions in APIKeyView or elsewhere before View.get_response
            return e.response
        except ValidationError as e:
            return JsonResponse(
                ErrorSchema(
                    id="validation_error",
                    message=f"Validation error: {e.message}",
                    url="",
                    # "errors": {field: e.errors[field] for field in e.errors},
                ),
                status_code=400,
            )
        except FormFieldMissingError as e:
            return JsonResponse(
                ErrorSchema(
                    id="missing_field",
                    message=f"Missing field: {e.field_name}",
                    url="",
                ),
                status_code=400,
            )
        except ForbiddenError403:
            return JsonResponse(
                ErrorSchema(
                    id="permission_denied",
                    message="Permission denied",
                    url="",
                ),
                status_code=403,
            )
        except NotFoundError404:
            return JsonResponse(
                ErrorSchema(
                    id="not_found",
                    message="Not found",
                    url="",
                ),
                status_code=404,
            )
        except Exception:
            logger.exception("Internal server error", extra={"request": self.request})
            return JsonResponse(
                ErrorSchema(
                    id="server_error",
                    message="Internal server error",
                    url="",
                ),
                status_code=500,
            )


class DeviceAuthorizeView(APIView):
    """
    Device authorization endpoint (RFC 8628).

    The device POSTs here to get a device_code and user_code pair.
    The user_code is displayed to the user, who visits the verification_uri
    to approve the request. The device polls DeviceTokenView with the device_code.
    """

    def post(self) -> ResponseBase:
        data = self.request.json_data if self.request.body else {}
        scope = data.get("scope", "")

        grant = DeviceGrant(
            scope=scope,
            expires_at=timezone.now()
            + datetime.timedelta(seconds=settings.API_DEVICE_GRANT_EXPIRES),
        )
        grant.save()

        response_data = {
            "device_code": grant.device_code,
            "user_code": grant.user_code,
            "verification_uri": self.get_verification_uri(),
            "expires_in": settings.API_DEVICE_GRANT_EXPIRES,
            "interval": grant.interval,
        }

        verification_uri_complete = self.get_verification_uri_complete(grant.user_code)
        if verification_uri_complete:
            response_data["verification_uri_complete"] = verification_uri_complete

        return JsonResponse(response_data)

    def get_verification_uri(self) -> str:
        """Return the URL where users visit to enter their code."""
        return settings.API_DEVICE_FLOW_VERIFICATION_URI

    def get_verification_uri_complete(self, user_code: str) -> str:
        """Return the full URL with the user code pre-filled, or empty string."""
        base = self.get_verification_uri()
        if base:
            separator = "&" if "?" in base else "?"
            return f"{base}{separator}code={user_code}"
        return ""


class DeviceTokenView(APIView):
    """
    Device token endpoint (RFC 8628).

    The device polls here with its device_code to check if the user
    has approved the authorization request. Returns the access token
    when authorized.
    """

    def post(self) -> ResponseBase:
        data = self.request.json_data if self.request.body else {}
        device_code = data.get("device_code", "")

        if not device_code:
            return JsonResponse(
                {
                    "error": "invalid_request",
                    "error_description": "device_code is required",
                },
                status_code=400,
            )

        try:
            grant = DeviceGrant.query.get(device_code=device_code)
        except DeviceGrant.DoesNotExist:
            return JsonResponse(
                {"error": "invalid_grant", "error_description": "Unknown device code"},
                status_code=400,
            )

        if grant.is_expired():
            return JsonResponse(
                {
                    "error": "expired_token",
                    "error_description": "The device code has expired",
                },
                status_code=400,
            )

        if grant.status == DeviceGrant.STATUS_DENIED:
            return JsonResponse(
                {
                    "error": "access_denied",
                    "error_description": "The user denied the request",
                },
                status_code=400,
            )

        if grant.status == DeviceGrant.STATUS_PENDING:
            return JsonResponse(
                {
                    "error": "authorization_pending",
                    "error_description": "The user has not yet approved the request",
                },
                status_code=400,
            )

        if grant.status == DeviceGrant.STATUS_AUTHORIZED and grant.api_key:
            return JsonResponse(
                {
                    "access_token": grant.api_key.token,
                    "token_type": "Bearer",
                }
            )

        # Shouldn't reach here, but handle gracefully
        return JsonResponse(
            {"error": "server_error", "error_description": "Unexpected grant state"},
            status_code=500,
        )
