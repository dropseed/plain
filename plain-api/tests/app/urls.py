import re
from typing import TypedDict

from plain.api.versioning import APIVersionChange, VersionedAPIView
from plain.api.views import APIView, JsonNotFoundView
from plain.exceptions import ValidationError
from plain.urls import Router, path


class TestView(APIView):
    def get(self):
        return {"message": "Hello, world!"}


class GreetingResponse(TypedDict):
    message: str


class TypedDictReturnView(APIView):
    def get(self) -> GreetingResponse:
        return GreetingResponse(message="Hello, typed!")


class TupleStatusReturnView(APIView):
    def post(self):
        return 201, {"id": 42, "created": True}


class JsonEchoView(APIView):
    """Echoes back json_data — used to exercise content-type handling."""

    def post(self):
        return self.request.json_data


class ValidationErrorView(APIView):
    """Re-raises whatever validation error shape the test asks for."""

    def post(self):
        data = self.request.json_data
        shape = data["shape"]
        if shape == "string":
            raise ValidationError("Single-string error")
        if shape == "dict":
            raise ValidationError({"password": ["This field is required."]})
        raise ValidationError(["List error"])


class ChangeToName(APIVersionChange):
    description = "'to' changed to 'name'"

    def transform_request_forward(self, request, data):
        if "to" in data:
            data["name"] = data.pop("to")


class ChangeMsgMessage(APIVersionChange):
    description = "'message' changed to 'msg' in the response"

    def transform_response_backward(self, response, data):
        if "message" in data:
            data["msg"] = data.pop("message")


class TestVersionedAPIView(VersionedAPIView):
    api_versions = {
        "v2": [ChangeToName, ChangeMsgMessage],
        "v1": [],
    }

    def post(self):
        data = self.request.json_data
        assert isinstance(data, dict)
        name = data["name"]
        return {"message": f"Hello, {name}!"}


class AppRouter(Router):
    namespace = ""
    urls = [
        path("test", TestView, name="test"),
        path("typed-dict-return", TypedDictReturnView, name="typed_dict_return"),
        path("tuple-status-return", TupleStatusReturnView, name="tuple_status_return"),
        path("test-versioned", TestVersionedAPIView, name="test_versioned"),
        path("validation-error", ValidationErrorView, name="validation_error"),
        path("json-echo", JsonEchoView, name="json_echo"),
        path(re.compile(r"^missing-.+$"), JsonNotFoundView, name="missing"),
    ]
