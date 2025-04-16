import json
from functools import cached_property

from plain.http import ResponseBadRequest
from plain.views import View
from plain.views.exceptions import ResponseException


class APIVersionChange:
    description: str = ""

    def transform_request_forward(self, request, data):
        """
        If this version of the API made a change in how a request is processed,
        (ex. the name of an input changed) then you can
        """
        pass

    def transform_response_backward(self, response, data):
        """
        Transform the response data for this version.

        We only transform the response data if we are moving backward to an older version.
        This is because the response data is always in the latest version.
        """
        pass


class VersionedAPIView(View):
    # API versions from newest to oldest
    api_versions: dict[str, list[APIVersionChange]] = {}
    api_version_header = "API-Version"
    default_api_version: str = ""

    @cached_property
    def api_version(self) -> str:
        return self.get_api_version()

    def get_api_version(self) -> str:
        version = ""

        if version_name := self.request.headers.get(self.api_version_header, ""):
            version = version_name
        elif default_version := self.get_default_api_version():
            version = default_version
        else:
            raise ResponseException(
                ResponseBadRequest(
                    f"Missing API version header '{self.api_version_header}'"
                )
            )

        if version in self.api_versions:
            return version
        else:
            raise ResponseException(
                ResponseBadRequest(
                    f"Invalid API version '{version_name}'. Valid versions are: {', '.join(self.api_versions.keys())}"
                )
            )

    def get_default_api_version(self) -> str:
        # If this view has an api_key, use its version name
        if api_key := getattr(self, "api_key", None):
            if api_key.api_version:
                # If the API key has a version, use that
                return api_key.api_version

        return self.default_api_version

    def get_response(self):
        if self.request.content_type == "application/json":
            self.transform_request(self.request)

        # Process the request normally
        response = super().get_response()

        if response.headers.get("Content-Type") == "application/json":
            self.transform_response(response)

        # Put the API version on the response
        response.headers[self.api_version_header] = self.api_version

        return response

    def transform_request(self, request):
        request_changes = []

        # Find the version being requested,
        # then get every change after that up to the latest
        changing = False
        for version, changes in reversed(self.api_versions.items()):
            if version == self.api_version:
                changing = True

            if changing:
                request_changes.extend(changes)

        if not request_changes:
            return

        # Get the original request JSON
        request_data = json.loads(request.body)

        # Transform the request data for this version
        for change in changes:
            change().transform_request_forward(request, request_data)

        # Update the request body with the transformed data
        request._body = json.dumps(request_data).encode("utf-8")

    def transform_response(self, response):
        response_changes = []

        # Get the changes starting AFTER the current version
        matching = False
        for version, changes in reversed(self.api_versions.items()):
            if matching:
                response_changes.extend(changes)

            if version == self.api_version:
                matching = True

        if not response_changes:
            # No changes to apply, just return
            return

        # Get the original response JSON
        response_data = json.loads(response.content)

        for change in reversed(response_changes):
            # Transform the response data for this version
            change().transform_response_backward(response, response_data)

        # Update the response body with the transformed data
        response.content = json.dumps(response_data).encode("utf-8")
