from plain.api.versioning import APIVersionChange, VersionedAPIView
from plain.api.views import APIView
from plain.urls import Router, path


class TestView(APIView):
    def get(self):
        return {"message": "Hello, world!"}


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
        name = self.request.data["name"]
        return {"message": f"Hello, {name}!"}


class AppRouter(Router):
    namespace = ""
    urls = [
        path("test", TestView, name="test"),
        path("test-versioned", TestVersionedAPIView, name="test_versioned"),
    ]
