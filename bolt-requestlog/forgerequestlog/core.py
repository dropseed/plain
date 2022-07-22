import datetime
import json
import os

import requests
from forgecore import Forge

from . import settings


class RequestLog:
    def __init__(self, *, request, response):
        self.request = request
        self.response = response

    @staticmethod
    def storage_path():
        return os.path.join(Forge().forge_tmp_dir, "requestlog")

    @classmethod
    def replay_request(cls, name):
        path = os.path.join(cls.storage_path(), f"{name}.json")
        with open(path, "r") as f:
            data = json.load(f)

        method = data["request"]["method"]

        if method == "GET":
            # Params are in absolute uri
            request_data = data["request"]["body"]
        elif method in ("POST", "PUT", "PATCH"):
            if data["request"]["querydict"]:
                request_data = data["request"]["querydict"]
            else:
                request_data = data["request"]["body"]

        # Cookies need to be passed as a dict, so that
        # they are passed through redirects
        data["request"]["headers"].pop("Cookie", None)

        response = requests.request(
            method,
            data["request"]["absolute_uri"],
            headers=data["request"]["headers"],
            cookies=data["request"]["cookies"],
            data=request_data,
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
            with open(path, "r") as f:
                log = json.load(f)
                log["name"] = os.path.splitext(filename)[0]
                # Convert timestamp back to datetime
                log["timestamp"] = datetime.datetime.fromtimestamp(log["timestamp"])
                logs.append(log)

        return logs

    @staticmethod
    def delete_old_logs():
        storage_path = RequestLog.storage_path()
        if not os.path.exists(storage_path):
            return

        filenames = os.listdir(storage_path)
        sorted_filenames = sorted(filenames, reverse=True)
        for filename in sorted_filenames[settings.REQUESTLOG_KEEP_LATEST() :]:
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
        }

    @staticmethod
    def request_as_dict(request):
        return {
            "method": request.method,
            "path": request.path,
            "full_path": request.get_full_path(),
            "querydict": request.POST.dict()
            if request.method == "POST"
            else request.GET.dict(),
            "cookies": request.COOKIES,
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
