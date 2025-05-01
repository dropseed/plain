import datetime
import json
import os
import sys
import traceback

import requests

from plain.runtime import PLAIN_TEMP_PATH, settings
from plain.signals import got_request_exception


class RequestLog:
    def __init__(self, *, request, response, exception=None):
        self.request = request
        self.response = response
        self.exception = exception

    @staticmethod
    def storage_path():
        return str(PLAIN_TEMP_PATH / "dev" / "requestlog")

    @classmethod
    def replay_request(cls, name):
        path = os.path.join(cls.storage_path(), f"{name}.json")
        with open(path) as f:
            data = json.load(f)

        method = data["request"]["method"]

        if method == "GET":
            # Params are in absolute uri
            request_data = data["request"]["body"].encode("utf-8")
        elif method in ("POST", "PUT", "PATCH"):
            if data["request"]["querydict"]:
                request_data = data["request"]["querydict"]
            else:
                request_data = data["request"]["body"].encode("utf-8")

        # Cookies need to be passed as a dict, so that
        # they are passed through redirects
        data["request"]["headers"].pop("Cookie", None)

        # TODO???
        if data["request"]["headers"].get("X-Forwarded-Proto", "") == "https,https":
            data["request"]["headers"]["X-Forwarded-Proto"] = "https"

        response = requests.request(
            method,
            data["request"]["absolute_uri"],
            headers=data["request"]["headers"],
            cookies=data["request"]["cookies"],
            data=request_data,
            timeout=5,
        )
        print("Replayed request", response)

    @staticmethod
    def load_json_logs():
        storage_path = RequestLog.storage_path()
        if not os.path.exists(storage_path):
            return []

        logs = []
        filenames = os.listdir(storage_path)
        sorted_filenames = sorted(filenames, reverse=True)
        for filename in sorted_filenames:
            path = os.path.join(storage_path, filename)
            with open(path) as f:
                log = json.load(f)
                log["name"] = os.path.splitext(filename)[0]
                # Convert timestamp back to datetime
                log["timestamp"] = datetime.datetime.fromtimestamp(log["timestamp"])
                try:
                    log["request"]["body_json"] = json.dumps(
                        json.loads(log["request"]["body"]), indent=2
                    )
                except json.JSONDecodeError:
                    pass
                logs.append(log)

        return logs

    @staticmethod
    def delete_old_logs():
        storage_path = RequestLog.storage_path()
        if not os.path.exists(storage_path):
            return

        filenames = os.listdir(storage_path)
        sorted_filenames = sorted(filenames, reverse=True)
        for filename in sorted_filenames[settings.DEV_REQUESTS_MAX :]:
            path = os.path.join(storage_path, filename)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    @staticmethod
    def clear():
        storage_path = RequestLog.storage_path()
        if not os.path.exists(storage_path):
            return

        filenames = os.listdir(storage_path)
        for filename in filenames:
            path = os.path.join(storage_path, filename)
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    def save(self):
        storage_path = self.storage_path()
        if not os.path.exists(storage_path):
            os.makedirs(storage_path)

        timestamp = datetime.datetime.now().timestamp()
        filename = f"{timestamp}.json"
        path = os.path.join(storage_path, filename)
        with open(path, "w+") as f:
            json.dump(self.as_dict(), f, indent=2)

        self.delete_old_logs()

    def as_dict(self):
        return {
            "timestamp": datetime.datetime.now().timestamp(),
            "request": self.request_as_dict(self.request),
            "response": self.response_as_dict(self.response),
            "exception": self.exception_as_dict(self.exception),
        }

    @staticmethod
    def request_as_dict(request):
        return {
            "method": request.method,
            "path": request.path,
            "full_path": request.get_full_path(),
            "querydict": request.data.dict()
            if request.method == "POST"
            else request.query_params.dict(),
            "cookies": request.cookies,
            # files?
            "absolute_uri": request.build_absolute_uri(),
            "body": request.body.decode("utf-8"),
            "headers": dict(request.headers),
        }

    @staticmethod
    def response_as_dict(response):
        try:
            content = response.content.decode("utf-8")
        except AttributeError:
            content = "<streaming_content>"

        return {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content,
        }

    @staticmethod
    def exception_as_dict(exception):
        if not exception:
            return None

        tb_string = "".join(traceback.format_tb(exception.__traceback__))

        try:
            args = json.dumps(exception.args)
        except TypeError:
            args = str(exception.args)

        return {
            "type": type(exception).__name__,
            "str": str(exception),
            "args": args,
            "traceback": tb_string,
        }


def should_capture_request(request):
    if not settings.DEBUG:
        return False

    if request.resolver_match and request.resolver_match.namespace == "dev":
        return False

    if request.path in settings.DEV_REQUESTS_IGNORE_PATHS:
        return False

    # This could be an attribute set on request or response
    # or something more dynamic
    if "querystats" in request.query_params:
        return False

    return True


class RequestsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.exception = None  # If an exception occurs, we want to remember it

        got_request_exception.connect(self.store_exception)

    def __call__(self, request):
        # Process it first, so we know the resolver_match
        response = self.get_response(request)

        if should_capture_request(request):
            RequestLog(
                request=request, response=response, exception=self.exception
            ).save()

        return response

    def store_exception(self, **kwargs):
        """
        The signal calls this at the right time,
        so we can use sys.exxception to capture.
        """
        self.exception = sys.exception()
