import functools
import mimetypes
import os
from email.utils import formatdate, parsedate
from io import BytesIO

from plain.http import (
    FileResponse,
    Http404,
    Response,
    ResponseNotModified,
    ResponseRedirect,
    StreamingResponse,
)
from plain.runtime import settings
from plain.urls import reverse
from plain.views import View

from .compile import get_compiled_path
from .finders import iter_assets
from .fingerprints import FINGERPRINT_LENGTH, get_fingerprinted_url_path


class AssetView(View):
    """
    Serve an asset file directly.

    This class could be subclassed to further tweak the responses or behavior.
    """

    def __init__(self, asset_path=None):
        # Allow a path to be passed in AssetView.as_view(path="...")
        self.asset_path = asset_path

    def get_url_path(self):
        return self.asset_path or self.url_kwargs["path"]

    def get(self):
        url_path = self.get_url_path()

        # Make a trailing slash work, but we don't expect it
        url_path = url_path.rstrip("/")

        if settings.DEBUG:
            absolute_path = self.get_debug_asset_path(url_path)
        else:
            absolute_path = self.get_asset_path(url_path)

            if settings.ASSETS_REDIRECT_ORIGINAL:
                if redirect_response := self.get_redirect_response(url_path):
                    return redirect_response

        self.check_asset_path(absolute_path)

        if encoded_path := self.get_encoded_path(absolute_path):
            absolute_path = encoded_path

        if range_response := self.get_range_response(absolute_path):
            return range_response

        if not_modified_response := self.get_conditional_response(absolute_path):
            return not_modified_response

        content_type, _ = mimetypes.guess_type(absolute_path)

        response = FileResponse(
            open(absolute_path, "rb"),
            filename=os.path.basename(absolute_path),
            content_type=content_type,
        )
        response.headers = self.update_headers(response.headers, absolute_path)
        return response

    def get_asset_path(self, path):
        """Get the path to the compiled asset"""
        compiled_path = os.path.abspath(get_compiled_path())
        asset_path = os.path.join(compiled_path, path)

        # Make sure we don't try to escape the compiled assests path
        if not os.path.commonpath([compiled_path, asset_path]) == compiled_path:
            raise Http404("Asset not found")

        return asset_path

    def get_debug_asset_path(self, path):
        """Make a "live" check to find the uncompiled asset in the filesystem"""
        for asset in iter_assets():
            if asset.url_path == path:
                return asset.absolute_path

    def check_asset_path(self, path):
        if not path:
            raise Http404("Asset not found")

        if not os.path.exists(path):
            raise Http404("Asset not found")

        if os.path.isdir(path):
            raise Http404("Asset is a directory")

    @functools.cache
    def get_last_modified(self, path):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None

        if mtime:
            return formatdate(mtime, usegmt=True)

    @functools.cache
    def get_etag(self, path):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None

        timestamp = int(mtime)
        size = self.get_size(path)
        return f'"{timestamp:x}-{size:x}"'

    @functools.cache
    def get_size(self, path):
        return os.path.getsize(path)

    def update_headers(self, headers, path):
        headers.setdefault("Access-Control-Allow-Origin", "*")

        # Always vary on Accept-Encoding
        vary = headers.get("Vary")
        if not vary:
            headers["Vary"] = "Accept-Encoding"
        elif vary == "*":
            pass
        elif "Accept-Encoding" not in vary:
            headers["Vary"] = vary + ", Accept-Encoding"

        # If the file is compressed, tell the browser
        if encoding := mimetypes.guess_type(path)[1]:
            headers.setdefault("Content-Encoding", encoding)

        is_immutable = self.is_immutable(path)

        if is_immutable:
            max_age = 10 * 365 * 24 * 60 * 60  # 10 years
            headers.setdefault("Cache-Control", f"max-age={max_age}, immutable")
        elif settings.DEBUG:
            # In development, cache for 1 second to avoid re-fetching the same file
            headers.setdefault("Cache-Control", "max-age=0")
        else:
            # Tell the browser to cache the file for 60 seconds if nothing else
            headers.setdefault("Cache-Control", "max-age=60")

        if not is_immutable:
            if last_modified := self.get_last_modified(path):
                headers.setdefault("Last-Modified", last_modified)
            if etag := self.get_etag(path):
                headers.setdefault("ETag", etag)

        if "Content-Disposition" in headers:
            # This header messes up Safari...
            # https://github.com/evansd/whitenoise/commit/93657cf88e14b919cb726864814617a6a639e507
            # At some point, should probably look at not using FileResponse at all?
            del headers["Content-Disposition"]

        return headers

    def is_immutable(self, path):
        """
        Determine whether an asset looks like it is immutable.

        Pattern matching based on fingerprinted filenames:
        - main.{fingerprint}.css
        - main.{fingerprint}.css.gz
        """
        base = os.path.basename(path)
        extension = None
        while extension != "":
            base, extension = os.path.splitext(base)
            if len(extension) == FINGERPRINT_LENGTH + 1 and extension[1:].isalnum():
                return True

        return False

    def get_encoded_path(self, path):
        """
        If the client supports compression, return the path to the compressed file.
        Otherwise, return the original path.
        """
        accept_encoding = self.request.headers.get("Accept-Encoding")
        if not accept_encoding:
            return

        if "br" in accept_encoding:
            br_path = path + ".br"
            if os.path.exists(br_path):
                return br_path

        if "gzip" in accept_encoding:
            gzip_path = path + ".gz"
            if os.path.exists(gzip_path):
                return gzip_path

    def get_redirect_response(self, path):
        """If the asset is not found, try to redirect to the fingerprinted path"""
        fingerprinted_url_path = get_fingerprinted_url_path(path)

        if not fingerprinted_url_path or fingerprinted_url_path == path:
            # Don't need to redirect if there is no fingerprinted path,
            # or we're already looking at it.
            return

        from .urls import AssetsRouter

        namespace = AssetsRouter.namespace

        return ResponseRedirect(
            redirect_to=reverse(f"{namespace}:asset", fingerprinted_url_path),
            headers={
                "Cache-Control": "max-age=60",  # Can cache this for a short time, but the fingerprinted path can change
            },
        )

    def get_conditional_response(self, path):
        """
        Support conditional requests (HTTP 304 response) based on ETag and Last-Modified headers.
        """
        if self.request.headers.get("If-None-Match") == self.get_etag(path):
            response = ResponseNotModified()
            response.headers = self.update_headers(response.headers, path)
            return response

        if "If-Modified-Since" in self.request.headers:
            if_modified_since = parsedate(self.request.headers["If-Modified-Since"])
            last_modified = parsedate(self.get_last_modified(path))
            if (
                if_modified_since
                and last_modified
                and if_modified_since >= last_modified
            ):
                response = ResponseNotModified()
                response.headers = self.update_headers(response.headers, path)
                return response

    def get_range_response(self, path):
        """
        Support range requests (HTTP 206 response).
        """
        range_header = self.request.headers.get("HTTP_RANGE")
        if not range_header:
            return None

        file_size = self.get_size(path)

        if not range_header.startswith("bytes="):
            return Response(
                status_code=416, headers=[("Content-Range", f"bytes */{file_size}")]
            )

        range_values = range_header.split("=")[1].split("-")
        start = int(range_values[0]) if range_values[0] else 0
        end = int(range_values[1]) if range_values[1] else float("inf")

        if start >= file_size:
            return Response(
                status_code=416, headers=[("Content-Range", f"bytes */{file_size}")]
            )

        end = min(end, file_size - 1)

        with open(path, "rb") as f:
            f.seek(start)
            content = f.read(end - start + 1)

        response = StreamingResponse(BytesIO(content), status_code=206)
        response.headers = self.update_headers(response.headers, path)
        response.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response.headers["Content-Length"] = str(end - start + 1)
        return response
