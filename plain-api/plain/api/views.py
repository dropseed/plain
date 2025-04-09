import datetime
import logging
from functools import cached_property
from typing import TYPE_CHECKING

from plain.exceptions import PermissionDenied, ValidationError
from plain.forms.exceptions import FormFieldMissingError
from plain.http import Http404, JsonResponse, Response
from plain.utils import timezone
from plain.utils.cache import patch_cache_control
from plain.views.base import View
from plain.views.csrf import CsrfExemptViewMixin
from plain.views.exceptions import ResponseException

from .models import APIKey

if TYPE_CHECKING:
    pass


logger = logging.getLogger("plain.api")


class APIKeyView(View):
    api_key_required = True

    @cached_property
    def api_key(self) -> APIKey | None:
        return self.get_api_key()

    def get_response(self) -> Response:
        if self.api_key:
            self.use_api_key()
        elif self.api_key_required:
            return JsonResponse(
                {
                    "message": "API key required",
                    "errors": {},
                },
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

    def get_api_key(self) -> APIKey | None:
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
                        {
                            "message": "Invalid Authorization header",
                            "errors": {},
                        },
                        status_code=400,
                    )
                )

            try:
                api_key = APIKey.objects.get(token=header_token)
            except APIKey.DoesNotExist:
                raise ResponseException(
                    JsonResponse(
                        {
                            "message": "Invalid API token",
                            "errors": {},
                        },
                        status_code=400,
                    )
                )

            if api_key.expires_at and api_key.expires_at < datetime.datetime.now():
                raise ResponseException(
                    JsonResponse(
                        {
                            "message": "API token has expired",
                            "errors": {},
                        },
                        status_code=400,
                    )
                )

            return api_key


class APIView(CsrfExemptViewMixin, View):
    def get_response(self):
        try:
            return super().get_response()
        except ResponseException as e:
            # Catch any response exceptions in APIKeyView or elsewhere before View.get_response
            return e.response
        except ValidationError as e:
            return JsonResponse(
                {
                    "message": "Invalid input",
                    "errors": {field: e.errors[field] for field in e.errors},
                },
                status_code=400,
            )
        except FormFieldMissingError as e:
            return JsonResponse(
                {
                    "message": "Invalid input",
                    "errors": {e.field_name: ["Missing field"]},
                },
                status_code=400,
            )
        except PermissionDenied:
            return JsonResponse(
                {
                    "message": "Permission denied",
                    "errors": {},
                },
                status_code=403,
            )
        except Http404:
            return JsonResponse(
                {
                    "message": "Not found",
                    "errors": {},
                },
                status_code=404,
            )
        except Exception:
            logger.exception("Internal server error", extra={"request": self.request})
            return JsonResponse(
                {
                    "message": "Internal server error",
                    "errors": {},
                },
                status_code=500,
            )
