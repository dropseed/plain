import datetime
import json
from typing import TYPE_CHECKING, Any

from plain.auth.views import AuthViewMixin
from plain.exceptions import ObjectDoesNotExist
from plain.views.base import View
from plain.views.csrf import CsrfExemptViewMixin
from plain.views.exceptions import ResponseException

from .responses import (
    HttpNoContentResponse,
    JsonResponse,
    JsonResponseBadRequest,
    JsonResponseCreated,
    JsonResponseList,
    ResponseBadRequest,
    ResponseNotFound,
)

if TYPE_CHECKING:
    from plain.forms import BaseForm

from .models import APIKey


class APIAuthViewMixin(AuthViewMixin):
    # Disable login redirects
    login_url = None

    def get_api_key(self) -> APIKey | None:
        if "Authorization" in self.request.headers:
            header_value = self.request.headers["Authorization"]
            try:
                header_token = header_value.split("Bearer ")[1]
            except IndexError:
                raise ResponseException(
                    ResponseBadRequest("Invalid Authorization header")
                )

            try:
                api_key = APIKey.objects.get(token=header_token)
            except APIKey.DoesNotExist:
                raise ResponseException(ResponseBadRequest("Invalid API token"))

            if api_key.expires_at and api_key.expires_at < datetime.datetime.now():
                raise ResponseException(ResponseBadRequest("API token has expired"))

            return api_key

    def check_auth(self) -> None:
        if not hasattr(self, "request"):
            raise AttributeError(
                "APIAuthViewMixin requires the request attribute to be set."
            )

        # If the user is already known, exit early
        if self.request.user:
            super().check_auth()
            return

        if api_key := self.get_api_key():
            # Put the api_key on the request so we can access it
            self.request.api_key = api_key

            # Set the user if api_key has that attribute (typically from a ForeignKey)
            # TODO OneToOneField is gone, so now this should get the users and error if there are multiple?
            # or we need to move this to user space instead
            if user := getattr(api_key, "user", None):
                self.request.user = user

        # Run the regular auth checks which will look for self.request.user
        super().check_auth()


class APIBaseView(View):
    # Empty by default, so you need to specifically enable the methods you want.
    allowed_http_methods = []

    form_class: type["BaseForm"] | None = None

    def object_to_dict(self, obj):  # Intentionally untyped
        raise NotImplementedError(
            f"object_to_dict() is not implemented on {self.__class__.__name__}"
        )

    def get_form_response(
        self,
    ) -> JsonResponse | JsonResponseCreated | JsonResponseBadRequest:
        if self.form_class is None:
            raise NotImplementedError(
                f"form_class is not set on {self.__class__.__name__}"
            )

        form = self.form_class(**self.get_form_kwargs())

        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def get_form_kwargs(self) -> dict[str, Any]:
        if not self.request.body:
            raise ResponseException(ResponseBadRequest("No JSON body provided"))

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            raise ResponseException(
                JsonResponseBadRequest({"error": "Unable to parse JSON"})
            )

        return {
            "data": data,
            "files": self.request.FILES,
        }

    def form_valid(self, form: "BaseForm") -> JsonResponse | JsonResponseCreated:
        """
        Used for PUT and PATCH requests.
        Can check self.request.method if you want different behavior.
        """
        object = form.save()  # type: ignore
        data = self.object_to_dict(object)

        if self.request.method == "POST":
            return JsonResponseCreated(
                data,
                json_dumps_params={
                    "sort_keys": True,
                },
            )
        else:
            return JsonResponse(
                data,
                json_dumps_params={
                    "sort_keys": True,
                },
            )

    def form_invalid(self, form: "BaseForm") -> JsonResponseBadRequest:
        return JsonResponseBadRequest(
            {"message": "Invalid input", "errors": form.errors.get_json_data()},
        )


class APIObjectListView(CsrfExemptViewMixin, APIBaseView):
    def load_objects(self) -> None:
        try:
            self.objects = self.get_objects()
        except ObjectDoesNotExist:
            # Custom 404 with no body
            raise ResponseException(ResponseNotFound())

        if not self.objects:
            # Also raise 404 if the object is None
            raise ResponseException(ResponseNotFound())

    def get_objects(self):  # Intentionally untyped for subclasses to type
        raise NotImplementedError(
            f"get_objects() is not implemented on {self.__class__.__name__}"
        )

    def get(self) -> JsonResponseList | ResponseNotFound | ResponseBadRequest:
        self.load_objects()
        # TODO paginate??
        data = [self.object_to_dict(obj) for obj in self.objects]
        return JsonResponseList(data)

    def post(
        self,
    ) -> JsonResponseCreated | ResponseNotFound | ResponseBadRequest:
        self.load_objects()
        return self.get_form_response()  # type: ignore


class APIObjectView(CsrfExemptViewMixin, APIBaseView):
    """Similar to a DetailView but without all of the context and template logic."""

    def load_object(self) -> None:
        try:
            self.object = self.get_object()
        except ObjectDoesNotExist:
            # Custom 404 with no body
            raise ResponseException(ResponseNotFound())

        if not self.object:
            # Also raise 404 if the object is None
            raise ResponseException(ResponseNotFound())

    def get_object(self):  # Intentionally untyped for subclasses to type
        """
        Get an instance of an object (typically a model instance).

        Authorization should be done here too.
        """
        raise NotImplementedError(
            f"get_object() is not implemented on {self.__class__.__name__}"
        )

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.object
        return kwargs

    def get(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        data = self.object_to_dict(self.object)
        return JsonResponse(data)

    def put(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        return self.get_form_response()

    def patch(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        return self.get_form_response()

    def delete(
        self,
    ) -> HttpNoContentResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        self.object.delete()
        return HttpNoContentResponse()
