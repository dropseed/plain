# from functools import cached_property

# from plain.http import ResponseBadRequest
# from plain.views import View
# from plain.views.exceptions import ResponseException


# class APIVersion:
#     name: str

#     # TODO parsing and dumping json over and over is wasteful...
#     # its almost like a pipeline of views? Pipeline is in the MRO, and calls all the children?
#     # then each Version(View) can use object_to_dict() and stuff? or just need to universalize the
#     # json dump and load

#     def transform_request(self, request):
#         # self.transform_request_data(request.data)
#         raise NotImplementedError(
#             "VersionedAPIView subclasses must implement transform_request()"
#         )

#     # def transform_request_data(self, data):
#     #     """
#     #     Transform the request data for this version.
#     #     """
#     #     return data

#     def transform_response(self, response):
#         raise NotImplementedError(
#             "VersionedAPIView subclasses must implement transform_response()"
#         )


# class VersionedAPIView(View):
#     # An ordered list of versions that are recognized.
#     api_versions: list[type[APIVersion]]
#     api_version_header = "API-Version"
#     default_api_version: type[APIVersion] | None = None

#     @cached_property
#     def api_version(self) -> type[APIVersion]:
#         return self.get_api_version()

#     def get_api_version(self) -> type[APIVersion]:
#         if version_name := self.request.headers.get(self.api_version_header, ""):
#             for v in self.api_versions:
#                 if v.name == version_name:
#                     return v

#             raise ResponseException(
#                 ResponseBadRequest(
#                     f"Invalid API version '{version_name}'. Valid versions are: {', '.join(v.name for v in self.api_versions)}"
#                 )
#             )

#         if default_version := self.get_default_api_version():
#             return default_version

#         raise ResponseException(
#             ResponseBadRequest(
#                 f"Missing API version header '{self.api_version_header}'"
#             )
#         )

#     def get_default_api_version(self) -> str:
#         # If this view has an api_key, use its version name
#         if api_key := getattr(self, "api_key", None):
#             if version_name := api_key.api_version_name:
#                 for v in self.api_versions:
#                     if v.name == version_name:
#                         return version_name

#                 raise ValueError(f"Invalid API key version '{version_name}'.")

#         return self.default_api_version

#     def _iter_api_versions_forward(self):
#         """
#         Iterate over the versions in the order they are defined in self.versions.
#         """
#         yielding = False
#         for version in self.api_versions:
#             if not yielding and version == self.api_version:
#                 yielding = True

#             if yielding:
#                 yield version

#     def _iter_api_versions_backward(self):
#         """
#         Iterate over the versions in reverse order.
#         """
#         yielding = False
#         for version in reversed(self.api_versions):
#             if not yielding and version == self.api_version:
#                 yielding = True

#             if yielding:
#                 yield version

#     def get_response(self):
#         for version in self._iter_api_versions_forward():
#             version().transform_request(self.request)

#         response = super().get_response()

#         for version in self._iter_api_versions_backward():
#             version().transform_response(response)

#         # Put the API version on the response
#         response.headers[self.api_version_header] = self.api_version.name

#         return response
