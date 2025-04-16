import datetime
import logging
from functools import cached_property

from plain.exceptions import PermissionDenied, ValidationError
from plain.forms.exceptions import FormFieldMissingError
from plain.http import Http404, JsonResponse, Response
from plain.utils import timezone
from plain.utils.cache import patch_cache_control
from plain.views.base import View
from plain.views.csrf import CsrfExemptViewMixin
from plain.views.exceptions import ResponseException

from . import openapi
from .schemas import ErrorSchema

# Allow plain.api to be used without plain.models
try:
    from .models import APIKey
except ImportError:
    APIKey = None

logger = logging.getLogger("plain.api")


# @openapi.response_typed_dict(400, ErrorSchema)
# @openapi.response_typed_dict(401, ErrorSchema)
class APIKeyView(View):
    api_key_required = True

    @cached_property
    def api_key(self):
        return self.get_api_key()

    def get_response(self) -> Response:
        if self.api_key:
            self.use_api_key()
        elif self.api_key_required:
            return JsonResponse(
                ErrorSchema(
                    id="api_key_required",
                    message="API key required",
                ),
                status_code=401,
            )

        response = super().get_response()
        # Make sure it at least has private as a default
        patch_cache_control(response, private=True)
        return response

    def use_api_key(self):
        """
        Use the API key for this request.

        Override this to perform other actions with a valid API key.
        """
        self.api_key.last_used_at = timezone.now()
        self.api_key.save(update_fields=["last_used_at"])

    def get_api_key(self):
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
                        ),
                        status_code=400,
                    )
                )

            try:
                api_key = APIKey.objects.get(token=header_token)
            except APIKey.DoesNotExist:
                raise ResponseException(
                    JsonResponse(
                        ErrorSchema(
                            id="invalid_api_token",
                            message="Invalid API token",
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
class APIView(CsrfExemptViewMixin, View):
    def get_response(self):
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
                    # "errors": {field: e.errors[field] for field in e.errors},
                ),
                status_code=400,
            )
        except FormFieldMissingError as e:
            return JsonResponse(
                ErrorSchema(
                    id="missing_field",
                    message=f"Missing field: {e.field_name}",
                ),
                status_code=400,
            )
        except PermissionDenied:
            return JsonResponse(
                ErrorSchema(
                    id="permission_denied",
                    message="Permission denied",
                ),
                status_code=403,
            )
        except Http404:
            return JsonResponse(
                ErrorSchema(
                    id="not_found",
                    message="Not found",
                ),
                status_code=404,
            )
        except Exception:
            logger.exception("Internal server error", extra={"request": self.request})
            return JsonResponse(
                ErrorSchema(
                    id="server_error",
                    message="Internal server error",
                ),
                status_code=500,
            )
